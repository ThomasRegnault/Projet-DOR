package web

import (
	"database/sql"
	"encoding/json"
	"io"
	"net/http"
	"os"
	"path/filepath"

	_ "modernc.org/sqlite"
)

type WEBSQLManager struct {
	DB *sql.DB
}

func NewWEBSQLManager(dbPath string) *WEBSQLManager {
	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		panic(err)
	}

	m := &WEBSQLManager{DB: db}
	m.initDB()
	return m
}

func (m *WEBSQLManager) initDB() {
	query := `
	CREATE TABLE IF NOT EXISTS messages (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		sender TEXT,
		receiver TEXT,
		type TEXT,
		content TEXT,
		filename TEXT,
		created_at DATETIME DEFAULT CURRENT_TIMESTAMP
	);`

	_, err := m.DB.Exec(query)
	if err != nil {
		panic(err)
	}

	os.MkdirAll("./uploads", 0755)
}

/* =========================
   STRUCT
========================= */

type Message struct {
	Sender   string `json:"sender"`
	Receiver string `json:"receiver"`
	Type     string `json:"type"`
	Content  string `json:"content"`
	Filename string `json:"filename"`
	Time     string `json:"time"`
}

func (m *WEBSQLManager) SendMessage(w http.ResponseWriter, r *http.Request) {
	var msg Message

	err := json.NewDecoder(r.Body).Decode(&msg)
	if err != nil {
		http.Error(w, "Invalid JSON", 400)
		return
	}

	_, err = m.DB.Exec(
		"INSERT INTO messages(sender, receiver, type, content, filename) VALUES(?,?,?,?,?)",
		msg.Sender, msg.Receiver, msg.Type, msg.Content, msg.Filename,
	)

	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}

func (m *WEBSQLManager) GetMessages(w http.ResponseWriter, r *http.Request) {
	sender := r.URL.Query().Get("sender")
	receiver := r.URL.Query().Get("receiver")

	rows, err := m.DB.Query(`
		SELECT sender, receiver, type, content, filename, created_at
		FROM messages
		WHERE (sender=? AND receiver=?) OR (sender=? AND receiver=?)
		ORDER BY id ASC
	`, sender, receiver, receiver, sender)

	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}
	defer rows.Close()

	var messages []Message

	for rows.Next() {
		var msg Message
		var created string

		rows.Scan(&msg.Sender, &msg.Receiver, &msg.Type, &msg.Content, &msg.Filename, &created)

		msg.Time = created
		messages = append(messages, msg)
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(messages)
}

func (m *WEBSQLManager) UploadFile(w http.ResponseWriter, r *http.Request) {

	file, header, err := r.FormFile("file")
	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}
	defer file.Close()

	// sécuriser le nom
	filename := filepath.Base(header.Filename)
	path := "./uploads/" + filename

	out, err := os.Create(path)
	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}
	defer out.Close()

	io.Copy(out, file)

	// récupérer infos message
	sender := r.FormValue("sender")
	receiver := r.FormValue("receiver")

	fileType := header.Header.Get("Content-Type")

	// sauvegarde en DB
	_, err = m.DB.Exec(
		"INSERT INTO messages(sender, receiver, type, content, filename) VALUES(?,?,?,?,?)",
		sender, receiver, fileType, "", path,
	)

	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{
		"path": path,
	})
}

func (m *WEBSQLManager) RegisterRoutes() {
	http.HandleFunc("/send", m.SendMessage)
	http.HandleFunc("/messages", m.GetMessages)
	http.HandleFunc("/upload", m.UploadFile)

	// servir fichiers upload
	http.Handle("/uploads/", http.StripPrefix("/uploads/", http.FileServer(http.Dir("./uploads"))))
}
