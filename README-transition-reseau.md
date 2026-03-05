# Transition localhost → Réseau réel (IP)

## Contexte

Jusqu'à présent, notre projet de Dynamic Onion Routing (DOR) fonctionnait entièrement en **localhost** : le serveur d'annuaire, les nœuds relais et les nœuds destinataires tournaient tous sur la même machine. Toutes les connexions TCP utilisaient `localhost` ou `127.0.0.1` comme adresse.

L'objectif de cette branche est de **supprimer toutes les dépendances à localhost** pour permettre au système de fonctionner sur un **réseau réel**, avec plusieurs machines physiques (ou virtuelles) qui communiquent entre elles via leurs adresses IP réelles.

---

## Principe général des modifications

Deux axes de changement ont été nécessaires :

Le **premier axe** concerne les connexions vers le serveur d'annuaire. Chaque nœud doit connaître l'adresse IP du serveur d'annuaire (qui peut tourner sur une autre machine). On a introduit une variable d'environnement `SERVER_ADDR` que chaque nœud lit au démarrage. Si elle n'est pas définie, la valeur par défaut reste `localhost:8080`, ce qui permet de continuer à tester en local sans rien changer.

Le **second axe** concerne les communications entre nœuds. Auparavant, un nœud était identifié uniquement par son port (ex: `4567`), et pour communiquer avec lui on faisait `localhost:4567`. Maintenant, un nœud est identifié par son adresse complète `ip:port` (ex: `192.168.1.2:4567`). Ce changement impacte toute la chaîne : le format des routes, l'encapsulation en oignon, le protocole RELAY, le serveur d'annuaire, et les commandes utilisateur.

---

## Détail des modifications par fichier

### 1. `node_server/model/NodeInfo.go`

Aucune modification. Ce fichier contenait déjà un champ `Ip string` dans la struct `NodeInfo`. C'est le serveur qui le remplissait en récupérant l'IP depuis `conn.RemoteAddr()`, mais cette information n'était pas exploitée jusqu'à maintenant.

---

### 2. `node_server/model/Node.go`

#### Ajout du champ `ServerAddr` dans la struct `Node`

On a ajouté un champ `ServerAddr string` à la struct `Node`. Ce champ stocke l'adresse du serveur d'annuaire (par exemple `192.168.1.10:8080`). Il est initialisé à la création du nœud et utilisé par toutes les méthodes qui ont besoin de contacter le serveur.

Avant, l'adresse `localhost:8080` était écrite en dur dans chaque méthode. Maintenant, chaque méthode utilise `n.ServerAddr`.

#### Modification de `GetNodesList()`

Cette méthode contacte le serveur pour récupérer la liste des nœuds. L'appel `net.Dial("tcp", "localhost:8080")` a été remplacé par `net.Dial("tcp", n.ServerAddr)`.

#### Modification de `Stop()`

Quand un nœud s'arrête, il envoie un message `QUIT` au serveur pour se désenregistrer. Même changement : `net.Dial("tcp", "localhost:8080")` remplacé par `net.Dial("tcp", n.ServerAddr)`.

#### Modification de `SendTo()`

C'est un changement fondamental. Cette fonction est utilisée à chaque fois qu'un nœud envoie un message à un autre nœud (que ce soit un message direct ou un relai).

Avant, elle prenait un `int` (le port) et construisait l'adresse avec `fmt.Sprintf("localhost:%d", targetPort)`. Maintenant, elle prend directement un `string` (l'adresse complète `ip:port`) et le passe tel quel à `net.Dial`.

Signature avant : `func (n *Node) SendTo(targetPort int, message string) error`
Signature après : `func (n *Node) SendTo(targetAddr string, message string) error`

#### Modification du handler `RELAY` dans `handlerroutine()`

Quand un nœud reçoit un message chiffré, il le déchiffre et trouve soit un `MSG` (message final), soit un `RELAY` (à transférer au nœud suivant).

Le format du RELAY a changé. Avant, c'était `RELAY:<port>:<payload_chiffré>`. Le nœud faisait un `SplitN(data, ":", 2)` pour extraire le port et le payload, puis appelait `SendTo(port, payload)`.

Maintenant, c'est `RELAY:<ip>:<port>:<payload_chiffré>`. Le nœud fait un `SplitN(data, ":", 3)` pour extraire l'IP, le port et le payload. Il reconstruit l'adresse complète avec `nextAddr = subParts[0] + ":" + subParts[1]`, puis appelle `SendTo(nextAddr, payload)`.

---

### 3. `node_server/node/main.go`

#### Lecture de `SERVER_ADDR` au démarrage

Au début de `main()`, on lit la variable d'environnement `SERVER_ADDR`. Si elle n'est pas définie, on utilise `localhost:8080` par défaut. Cette valeur est passée à `NewNode()` qui la stocke dans le champ `ServerAddr` de la struct `Node`.

```go
serverAddr := os.Getenv("SERVER_ADDR")
if serverAddr == "" {
    serverAddr = "localhost:8080"
}
node, err := NewNode(id, serverAddr)
```

#### Modification de `NewNode()`

La fonction accepte maintenant un second paramètre `serverAddr string` et le stocke dans la struct `Node`.

#### Modification de `FetchKeyFromServer()`

Cette fonction demande au serveur d'annuaire la clé publique d'un nœud donné. Elle prend maintenant une adresse `string` (au lieu d'un port `int`) et l'adresse du serveur.

Le message envoyé au serveur passe de `GET_KEY:<port>` à `GET_KEY:<ip>:<port>`.

#### Modification du dictionnaire `publicKeys`

Le dictionnaire local qui associe un nœud à sa clé publique utilisait `map[int]*rsa.PublicKey` (clé = port). Il utilise maintenant `map[string]*rsa.PublicKey` (clé = adresse `ip:port`).

#### Modification de `Encapsulator_func()`

C'est la fonction qui construit l'oignon en encapsulant le message dans plusieurs couches de chiffrement. Le paramètre `route` passe de `[]int` (liste de ports) à `[]string` (liste d'adresses `ip:port`).

Le format de la couche RELAY passe de `RELAY:<port>:<payload_chiffré>` à `RELAY:<ip>:<port>:<payload_chiffré>`, via `fmt.Sprintf("RELAY:%s:%s", targetAddr, encoded)`.

#### Modification des commandes utilisateur

Toutes les commandes interactives ont été mises à jour pour utiliser des adresses `ip:port` :

**FETCH** — Avant : `FETCH:<port>`. Après : `FETCH:<ip>:<port>`. Se connecte directement au nœud cible pour récupérer sa clé publique.

**MSG** — Avant : `MSG:<port>:<message>`. Après : `MSG:<ip>:<port>:<message>`. Le split passe de 2 à 3 parties pour extraire l'IP, le port et le message. L'adresse est reconstruite avec `dstAddr = subParts[0] + ":" + subParts[1]`.

**RELAY** — C'est la commande qui a le plus changé structurellement. Avant : `RELAY:<port1>:<port2>:...:<message>` avec `:` comme séparateur. Le problème est qu'une adresse `ip:port` contient elle-même un `:`, donc on ne peut plus utiliser `:` comme séparateur entre les nœuds de la route. La solution : utiliser la **virgule** comme séparateur. Après : `RELAY:<ip1>:<port1>,<ip2>:<port2>,...,<message>`. Le message est après la dernière virgule.

**SEND** — Avant : `SEND:<nbr>:<port>:<message>`. Après : `SEND:<nbr>:<ip>:<port>:<message>`. Le parsing de la liste retournée par le serveur a aussi changé car le format passe de `name|port|key` à `name|ip|port|key` (4 champs au lieu de 3).

---

### 4. `node_server/List_Serveur/serveur.go`

#### Modification de `getNodesList()`

Le format de la liste renvoyée aux nœuds inclut maintenant l'IP. Avant : `name|port|key`. Après : `name|ip|port|key`. Le `fmt.Sprintf` passe de `"%s|%d|%s"` à `"%s|%s|%d|%s"` avec l'ajout de `info.Ip`.

#### Modification du handler `GET_KEY`

Le serveur recevait `GET_KEY:<port>` et cherchait un nœud par son port uniquement. Maintenant il reçoit `GET_KEY:<ip>:<port>` et cherche par IP **et** port. Cela évite les conflits si deux machines différentes utilisent le même port.

Le parsing passe de `parts[1]` (port) à `parts[1]` (IP) + `parts[2]` (port), et la condition de recherche passe de `node.Port == port` à `node.Ip == ip && node.Port == port`.

#### Modification de `TestPing()`

Le serveur ping périodiquement les nœuds pour vérifier qu'ils sont toujours actifs. L'adresse de ping passe de `fmt.Sprintf("localhost:%d", node.Port)` à `fmt.Sprintf("%s:%d", node.Ip, node.Port)`.

#### Modification de `showNodes()`

L'affichage des nœuds dans la console du serveur inclut maintenant l'IP : `fmt.Printf("  . %s - Addr: %s:%d, Key: %s\n", info.Name, info.Ip, info.Port, info.PublicKey)`.

---

### 5. Scripts de lancement

#### `start_node.sh`

Ajout de la variable `SERVER_ADDR="${SERVER_ADDR:-localhost:8080}"` et passage de `SERVER_ADDR=$SERVER_ADDR` aux commandes de lancement des nœuds.

#### `start_nodes_tmux.sh`

Même principe : ajout de `SERVER_ADDR="${SERVER_ADDR:-localhost:8080}"` en haut du script, et passage de la variable aux fenêtres tmux des nœuds.

---

## Comment utiliser

### En local (comme avant, rien ne change)

```bash
./start_nodes_tmux.sh -n 4
```

Les nœuds utilisent `localhost:8080` par défaut.

### En réseau réel

Supposons 3 machines :
- **Machine A** (192.168.1.10) : serveur d'annuaire
- **Machine B** (192.168.1.11) : nœud 1
- **Machine C** (192.168.1.12) : nœud 2

Sur la machine A, lancer le serveur :
```bash
cd node_server/List_Serveur && go run serveur.go
```

Sur la machine B, lancer un nœud :
```bash
SERVER_ADDR=192.168.1.10:8080 go run main.go node-1
```

Sur la machine C, lancer un autre nœud :
```bash
SERVER_ADDR=192.168.1.10:8080 go run main.go node-2
```

Les commandes utilisent maintenant des adresses IP complètes :
```
MSG:192.168.1.12:4567:Salut depuis la machine B !
SEND:1:192.168.1.12:4567:Message auto-routé
RELAY:192.168.1.12:4567,192.168.1.11:8901,Message via route manuelle
```

---

## Prochaines étapes

### Écoute sur 0.0.0.0

Actuellement, les nœuds écoutent avec `net.Listen("tcp", ":0")` ce qui devrait accepter les connexions de toutes les interfaces. Cependant, il faut vérifier que le serveur d'annuaire (qui écoute sur `:8080`) est bien accessible depuis les autres machines. Selon la configuration réseau et le pare-feu, il pourrait être nécessaire de spécifier explicitement `0.0.0.0:8080`.

### Gestion de l'adresse locale du nœud dans SEND

Dans la commande `SEND`, le nœud doit s'exclure de la route aléatoire. Actuellement, on reconstruit l'adresse locale du nœud à partir de `ServerAddr`, ce qui n'est pas fiable (l'IP du nœud n'est pas forcément la même que celle du serveur). Il faudrait soit que le nœud connaisse sa propre IP (passée en paramètre ou détectée), soit que le serveur renvoie l'IP du nœud dans la réponse `INIT_ACK`.

### Pare-feu et ports

Pour que le réseau fonctionne, les ports utilisés par les nœuds (attribués dynamiquement) doivent être accessibles depuis les autres machines. Il faudra soit ouvrir une plage de ports, soit permettre aux nœuds de choisir un port fixe configurable.

### Sécurité du protocole

Le protocole entre le nœud et le serveur d'annuaire (INIT, GET_LIST, GET_KEY) n'est pas chiffré. Sur un réseau réel, un attaquant pourrait intercepter les clés publiques ou la liste des nœuds. Une amélioration serait d'ajouter du TLS pour ces communications.

### Tests automatisés

Mettre en place des tests qui simulent un réseau multi-machines (par exemple avec Docker Compose ou des conteneurs) pour valider automatiquement le bon fonctionnement du routage en oignon en conditions réseau réelles.
