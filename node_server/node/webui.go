package main

import (
	"bufio"
	"crypto/rsa"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"project/node_server/model"
)

// ─────────────────────────────────────────────────────────────
// Broker SSE
// ─────────────────────────────────────────────────────────────

type logBroker struct {
	mu   sync.Mutex
	subs map[chan string]struct{}
}

var broker = &logBroker{subs: make(map[chan string]struct{})}

func broadcastLog(line string) {
	broker.mu.Lock()
	defer broker.mu.Unlock()
	for ch := range broker.subs {
		select {
		case ch <- line:
		default:
		}
	}
}

func (b *logBroker) subscribe() chan string {
	ch := make(chan string, 128)
	b.mu.Lock()
	b.subs[ch] = struct{}{}
	b.mu.Unlock()
	return ch
}

func (b *logBroker) unsubscribe(ch chan string) {
	b.mu.Lock()
	delete(b.subs, ch)
	b.mu.Unlock()
}

// ─────────────────────────────────────────────────────────────
// startStdoutBridge — intercepte os.Stdout pour diffuser les
// fmt.Println / fmt.Printf vers le SSE sans rien modifier dans main.go
// Appeler au tout début de main(), avant tout fmt.Println
// ─────────────────────────────────────────────────────────────

func startStdoutBridge() {
	r, w, err := os.Pipe()
	if err != nil {
		return
	}
	realStdout := os.Stdout
	os.Stdout = w

	go func() {
		scanner := bufio.NewScanner(r)
		for scanner.Scan() {
			line := scanner.Text()
			realStdout.Write([]byte(line + "\n"))
			broadcastLog(line)
		}
	}()
}

// ─────────────────────────────────────────────────────────────
// startWebUI — signature exacte appelée dans main.go :
//   startWebUI(node, serverAddr, publicKeys)
// ─────────────────────────────────────────────────────────────

func startWebUI(n *model.Node, srvAddr string, keys map[string]CachedKey) {
	port := 9090
	if p := os.Getenv("WEB_PORT"); p != "" {
		if v, err := strconv.Atoi(p); err == nil {
			port = v
		}
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/", handleIndex)
	mux.HandleFunc("/cmd", makeHandleCmd(n, keys, srvAddr))
	mux.HandleFunc("/nodes", makeHandleNodes(n))
	mux.HandleFunc("/logs", handleLogs)

	addr := fmt.Sprintf(":%d", port)
	fmt.Printf("[web] Interface disponible sur http://localhost%s\n", addr)

	go func() {
		if err := http.ListenAndServe(addr, mux); err != nil {
			fmt.Printf("[web] ERREUR serveur HTTP : %v\n", err)
		}
	}()
}

// ─────────────────────────────────────────────────────────────
// GET /
// ─────────────────────────────────────────────────────────────

func handleIndex(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	fmt.Fprint(w, webPage)
}

// ─────────────────────────────────────────────────────────────
// POST /cmd
// ─────────────────────────────────────────────────────────────

type cmdRequest struct {
	Cmd  string `json:"Cmd"`
	Mode string `json:"Mode"`
}

func makeHandleCmd(n *model.Node, keys map[string]CachedKey, srvAddr string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var req cmdRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "bad json", http.StatusBadRequest)
			return
		}
		go processCmd(strings.TrimSpace(req.Cmd), strings.TrimSpace(req.Mode), n, keys, srvAddr)
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"ok":true}`)
	}
}

func processCmd(input, mode string, n *model.Node, keys map[string]CachedKey, srvAddr string) {
	if input == "" {
		return
	}

	parts := strings.SplitN(input, ":", 2)
	cmd := strings.ToUpper(strings.TrimSpace(parts[0]))
	var data string
	if len(parts) > 1 {
		data = parts[1]
	}

	nodeAddr := fmt.Sprintf("%s:%d", n.NodeIP, n.Port)

	switch cmd {

	case "FETCH":
		targetAddr := data
		conn, err := net.Dial("tcp", targetAddr)
		if err != nil {
			fmt.Println("Erreur connexion:", err)
			return
		}
		conn.Write([]byte("GET_PUBKEY\n"))
		reader := bufio.NewReader(conn)
		pubBase64Raw, _ := reader.ReadString('\n')
		conn.Close()

		pubBytes, _ := base64.StdEncoding.DecodeString(strings.TrimSpace(pubBase64Raw))
		pubKeyInterface, err := x509.ParsePKIXPublicKey(pubBytes)
		if err != nil {
			fmt.Println("Erreur decodage clé:", err)
			return
		}
		if pubKey, ok := pubKeyInterface.(*rsa.PublicKey); ok {
			keys[targetAddr] = CachedKey{Key: pubKey, ExpiresAt: time.Now().Add(30 * time.Second)}
			fmt.Printf("Enregistrement de la clé (publique) de %s réalisé avec succès!\n", targetAddr)
		}

	case "MSG":
		subParts := strings.SplitN(data, ":", 3)
		if len(subParts) < 3 {
			fmt.Println("Invalid MSG format. Use MSG:<ip>:<port>:<message>")
			return
		}
		dstAddr := subParts[0] + ":" + subParts[1]
		msg := subParts[2]
		if mode == "auth" {
			msg = "AUTH:" + n.ID + ":" + msg
		}
		onion, _, _, err := Encapsulator_func(msg, []string{dstAddr}, nil, keys, srvAddr, nodeAddr)
		if err != nil {
			fmt.Println("Erreur Encapsulator_func:", err)
			return
		}
		if err := n.SendTo(dstAddr, onion); err != nil {
			fmt.Println("Error sending message:", err)
		}

	case "RELAY":
		lastComma := strings.LastIndex(data, ",")
		if lastComma == -1 {
			fmt.Println("Format: RELAY:<ip>:<port>,<ip>:<port>,...,<message>")
			return
		}
		addrsStr := strings.Split(data[:lastComma], ",")
		message := data[lastComma+1:]
		if mode == "auth" {
			message = "AUTH:" + n.ID + ":" + message
		}
		var route []string
		for _, addr := range addrsStr {
			route = append(route, strings.TrimSpace(addr))
		}
		onion, _, _, err := Encapsulator_func(message, route, nil, keys, srvAddr, nodeAddr)
		if err != nil {
			fmt.Println("Erreur Encapsulator_func:", err)
			return
		}
		if err := n.SendTo(route[0], onion); err != nil {
			fmt.Println("Erreur:", err)
		}

	case "SEND":
		subParts := strings.SplitN(data, ":", 4)
		if len(subParts) < 4 {
			fmt.Println("Format: SEND:<nbr_relays>:<ip>:<port>:<message>")
			return
		}
		numRelays, err := strconv.Atoi(subParts[0])
		if err != nil {
			fmt.Println("Error parsing relay number:", err)
			return
		}
		destAddr := subParts[1] + ":" + subParts[2]
		message := subParts[3]
		if mode == "auth" {
			message = "AUTH:" + n.ID + ":" + message
		}
		go SendWithRetry(n, srvAddr, destAddr, message, numRelays, keys, 3, 0, time.Now())

	case "LIST":
		list, err := n.GetNodesList()
		if err != nil {
			fmt.Println("Error:", err)
		} else {
			fmt.Println(list)
		}

	case "REGEN":
		if err := n.RegenerateKeys(); err != nil {
			fmt.Println("Erreur lors de la régénération:", err)
		} else {
			fmt.Println("Clé RSA régénérée avec succès.")
		}

	case "QUIT":
		fmt.Println("Shutting down node...")
		n.Stop()

	default:
		fmt.Println("Unknown command:", cmd)
	}
}

// ─────────────────────────────────────────────────────────────
// GET /nodes
// ─────────────────────────────────────────────────────────────

func makeHandleNodes(n *model.Node) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		list, err := n.GetNodesList()
		if err != nil || list == "" {
			list = "LIST:empty"
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"list": list})
	}
}

// ─────────────────────────────────────────────────────────────
// GET /logs — Server-Sent Events
// ─────────────────────────────────────────────────────────────

func handleLogs(w http.ResponseWriter, r *http.Request) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming not supported", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")

	ch := broker.subscribe()
	defer broker.unsubscribe(ch)

	ctx := r.Context()
	for {
		select {
		case <-ctx.Done():
			return
		case line := <-ch:
			safe := strings.ReplaceAll(line, "\n", " ")
			fmt.Fprintf(w, "data: %s\n\n", safe)
			flusher.Flush()
		}
	}
}
