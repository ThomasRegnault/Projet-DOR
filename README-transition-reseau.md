# Transition localhost → Réseau réel (IP)

## Principe général des modifications

Les modifications sont organisées en **5 axes** :

**Axe 1 — Adresse du serveur configurable** : Chaque nœud doit connaître l'adresse IP du serveur d'annuaire (qui peut tourner sur une autre machine). On a introduit une variable d'environnement `SERVER_ADDR` que chaque nœud lit au démarrage. Si elle n'est pas définie, la valeur par défaut reste `localhost:8080`, ce qui permet de continuer à tester en local sans rien changer.

**Axe 2 — Identification des nœuds par ip:port** : Auparavant, un nœud était identifié uniquement par son port (ex: `4567`), et pour communiquer avec lui on faisait `localhost:4567`. Maintenant, un nœud est identifié par son adresse complète `ip:port` (ex: `192.168.1.2:4567`). Ce changement impacte toute la chaîne : le format des routes, l'encapsulation en oignon, le protocole RELAY, le serveur d'annuaire, et les commandes utilisateur.

**Axe 3 — Écoute sur toutes les interfaces (0.0.0.0)** : Le serveur et les nœuds écoutent explicitement sur `0.0.0.0` pour accepter les connexions depuis n'importe quelle machine du réseau, pas seulement depuis localhost.

**Axe 4 — Détection automatique de l'IP du nœud** : Quand un nœud s'enregistre auprès du serveur, le serveur lui renvoie son adresse IP (telle que vue par le serveur) dans la réponse `INIT_ACK`. Le nœud stocke cette IP et l'utilise pour s'identifier dans le réseau (notamment pour s'exclure des routes aléatoires dans la commande `SEND`).

**Axe 5 — Configuration pare-feu** : Sur Windows, des règles de pare-feu sont nécessaires pour autoriser les connexions TCP entrantes sur le port 8080 (serveur) et sur les ports dynamiques des nœuds.

---

## Détail des modifications par fichier

### 1. `node_server/model/NodeInfo.go`

Aucune modification. Ce fichier contenait déjà un champ `Ip string` dans la struct `NodeInfo`. C'est le serveur qui le remplissait en récupérant l'IP depuis `conn.RemoteAddr()`, mais cette information n'était pas exploitée jusqu'à maintenant.

---

### 2. `node_server/model/Node.go`

#### Ajout des champs `ServerAddr` et `NodeIP` dans la struct `Node`

On a ajouté deux champs à la struct `Node` :

- `ServerAddr string` : stocke l'adresse du serveur d'annuaire (par exemple `192.168.1.10:8080`). Initialisé à la création du nœud et utilisé par toutes les méthodes qui contactent le serveur.
- `NodeIP string` : stocke l'adresse IP publique du nœud telle que vue par le serveur (par exemple `192.168.1.11`). Rempli automatiquement lors de l'enregistrement via `INIT_ACK`.

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

#### Suppression de l'import `strconv`

Le package `strconv` était utilisé dans le handler RELAY pour convertir le port avec `strconv.Atoi()`. Comme on manipule maintenant directement des adresses `string`, cet import n'est plus nécessaire et a été supprimé.

#### Modification de `JoinServerList()`

Le parsing de la réponse `INIT_ACK` a été enrichi. Avant, le nœud vérifiait simplement que la réponse commençait par `INIT_ACK`. Maintenant, le serveur renvoie `INIT_ACK:<n>:<ip>` et le nœud extrait son IP pour la stocker dans `n.NodeIP` :

```go
if strings.HasPrefix(response, "INIT_ACK") {
    ackParts := strings.SplitN(response, ":", 3)
    if len(ackParts) >= 3 {
        n.NodeIP = ackParts[2]
    }
    fmt.Printf("[%s] Registered to directory server (IP: %s)\n", n.ID, n.NodeIP)
    return nil
}
```

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

La fonction accepte maintenant un second paramètre `serverAddr string` et le stocke dans la struct `Node`. De plus, l'adresse d'écoute est passée de `":0"` à `"0.0.0.0:0"` pour écouter explicitement sur toutes les interfaces réseau.

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

**SEND** — Avant : `SEND:<nbr>:<port>:<message>`. Après : `SEND:<nbr>:<ip>:<port>:<message>`. Le parsing de la liste retournée par le serveur a aussi changé car le format passe de `name|port|key` à `name|ip|port|key` (4 champs au lieu de 3). L'exclusion du nœud courant de la route utilise maintenant `node.NodeIP` (l'IP reçue du serveur) au lieu de tenter de la reconstruire depuis `ServerAddr`.

---

### 4. `node_server/List_Serveur/serveur.go`

#### Écoute sur `0.0.0.0:8080`

Le serveur écoutait sur `":8080"`. On a changé en `"0.0.0.0:8080"` pour s'assurer qu'il accepte les connexions depuis toutes les interfaces réseau. C'est indispensable pour que des machines distantes puissent se connecter au serveur.

#### Modification de `getNodesList()`

Le format de la liste renvoyée aux nœuds inclut maintenant l'IP. Avant : `name|port|key`. Après : `name|ip|port|key`. Le `fmt.Sprintf` passe de `"%s|%d|%s"` à `"%s|%s|%d|%s"` avec l'ajout de `info.Ip`.

#### Modification du handler `INIT`

La réponse `INIT_ACK` inclut maintenant l'IP du nœud telle que vue par le serveur. Avant : `INIT_ACK:<n>`. Après : `INIT_ACK:<n>:<ip>`. Cela permet au nœud de connaître sa propre adresse IP sans avoir à la détecter lui-même.

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

## Guide d'utilisation complet

### Mode local (comme avant, rien ne change)

```bash
./start_nodes_tmux.sh -n 4
```

Les nœuds utilisent `localhost:8080` par défaut. Tout fonctionne comme avant nos modifications.

---

### Mode réseau réel

#### Prérequis

- Go installé sur toutes les machines (`go version` pour vérifier)
- Le code du projet présent sur chaque machine (via `git clone`)
- Les machines doivent être sur le **même réseau local** (même sous-réseau IP)
- Se placer sur la bonne branche : `git checkout feature/transition-from-localhost`

#### Configuration pare-feu (Windows uniquement)

Sur Windows, ouvrir PowerShell **en administrateur** et exécuter :

```powershell
New-NetFirewallRule -DisplayName "Allow ICMP" -Protocol ICMPv4 -Action Allow
New-NetFirewallRule -DisplayName "Allow DOR Server" -Protocol TCP -LocalPort 8080 -Action Allow
New-NetFirewallRule -DisplayName "Allow DOR Nodes" -Protocol TCP -LocalPort 49000-65535 -Action Allow
```

La première règle autorise le ping (utile pour tester la connectivité). La deuxième ouvre le port 8080 pour le serveur d'annuaire. La troisième ouvre la plage de ports dynamiques utilisés par les nœuds.

Sur Linux, si le pare-feu est actif :

```bash
sudo ufw allow 8080/tcp
sudo ufw allow 49000:65535/tcp
```

#### Trouver les adresses IP

Sur Windows :
```
ipconfig
```
Chercher l'adresse IPv4 sous la carte Wi-Fi ou Ethernet (ex: `192.168.1.71`).

Sur Linux :
```bash
ip addr
```
ou
```bash
hostname -I
```

#### Vérifier la connectivité entre les machines

Depuis chaque machine, vérifier qu'on peut atteindre les autres :

```bash
ping 192.168.1.71
```

Si le ping ne répond pas, vérifier le pare-feu.

#### Lancer le serveur d'annuaire

Sur la machine qui fera office de serveur (ex: `192.168.1.71`) :

```bash
cd node_server/List_Serveur
go run serveur.go
```

Le serveur affiche `Directory Server on port 8080`.

#### Lancer les nœuds

Sur chaque machine, lancer un nœud en lui indiquant l'adresse du serveur.

Sur Windows (PowerShell) :
```powershell
cd node_server\node
$env:SERVER_ADDR="192.168.1.71:8080"
go run main.go node-1
```

Sur Linux :
```bash
cd node_server/node
SERVER_ADDR=192.168.1.71:8080 go run main.go node-2
```

Chaque nœud doit afficher :
```
[node-X] Started in port : XXXXX
[node-X] Registered to directory server (IP: 192.168.1.XX)
```

L'IP affichée est celle détectée par le serveur. C'est cette IP qui sera utilisée pour le routage.

#### Vérifier l'enregistrement

Dans le terminal du serveur, taper `LIST` :

```
=== Noeuds connectés ===
  . node-1 - Addr: 192.168.1.71:52637, Key: MIIBIjAN...
  . node-2 - Addr: 192.168.1.90:42003, Key: MIIBIjAN...
Total: 2
```

Les IP doivent être **différentes** si les nœuds sont sur des machines différentes.

---

### Commandes disponibles

#### MSG — Message direct chiffré

Envoie un message directement à un nœud en le chiffrant avec sa clé publique.

```
MSG:<ip>:<port>:<message>
```

Exemple :
```
MSG:192.168.1.90:42003:Salut depuis Windows !
```

#### RELAY — Route manuelle chiffrée

Envoie un message via une route définie manuellement. Chaque nœud intermédiaire déchiffre une couche et relaye au suivant. Les adresses sont séparées par des **virgules**, le message est après la dernière virgule.

```
RELAY:<ip1>:<port1>,<ip2>:<port2>,...,<message>
```

Exemple (passer par node-2 avant d'arriver à node-3) :
```
RELAY:192.168.1.90:42003,192.168.1.71:63998,Message secret multi-hop
```

#### SEND — Route automatique aléatoire

Construit automatiquement une route aléatoire en récupérant la liste des nœuds depuis le serveur. Le premier paramètre est le nombre de relais intermédiaires souhaités.

```
SEND:<nbr_relais>:<ip>:<port>:<message>
```

Exemple (1 relai aléatoire avant la destination) :
```
SEND:1:192.168.1.90:42003:Message auto-routé !
```

Le nœud affiche la route choisie :
```
Route automatique: [192.168.1.71:63998 192.168.1.90:42003]
```

Il faut au minimum 3 nœuds enregistrés pour utiliser `SEND` avec 1 relai (l'expéditeur, le relai, et la destination).

#### FETCH — Récupérer une clé publique

Se connecte directement à un nœud pour récupérer sa clé publique et la stocker localement.

```
FETCH:<ip>:<port>
```

#### LIST — Afficher les nœuds enregistrés

Interroge le serveur et affiche la liste de tous les nœuds.

```
LIST:
```

#### QUIT — Quitter proprement

Se désenregistre du serveur et arrête le nœud.

```
QUIT:
```

---

### Test avec VirtualBox (exemple validé)

Voici la procédure exacte qui a été testée et validée :

**Configuration VirtualBox** :
1. Éteindre la VM
2. Configuration → Réseau → Adaptateur 1 → Mode : **Accès par pont** (Bridged Adapter)
3. Sélectionner la carte Wi-Fi dans le champ "Nom"
4. Démarrer la VM

**Machine Windows (192.168.1.71)** — 3 terminaux PowerShell :

Terminal 1 (serveur) :
```powershell
cd node_server\List_Serveur
go run serveur.go
```

Terminal 2 (node-1) :
```powershell
cd node_server\node
$env:SERVER_ADDR="192.168.1.71:8080"
go run main.go node-1
```

Terminal 3 (node-2) :
```powershell
cd node_server\node
$env:SERVER_ADDR="192.168.1.71:8080"
go run main.go node-2
```

**VM Linux (192.168.1.90)** — 1 terminal :

```bash
cd Projet-DOR/node_server/node
SERVER_ADDR=192.168.1.71:8080 go run main.go node-vm
```

**Tests effectués et validés** :

1. `LIST` sur le serveur → 3 nœuds avec 2 IP différentes
2. `MSG:192.168.1.90:42003:Hello` depuis Windows → message reçu sur la VM
3. `MSG:192.168.1.71:52637:Hello` depuis la VM → message reçu sur Windows
4. `SEND:1:192.168.1.71:52637:Test` depuis la VM → routage en oignon via un relai sur une autre machine

---

## Prochaines étapes possibles

### Sécurité du protocole

Le protocole entre le nœud et le serveur d'annuaire (INIT, GET_LIST, GET_KEY) n'est pas chiffré. Sur un réseau réel, un attaquant pourrait intercepter les clés publiques ou la liste des nœuds. Une amélioration serait d'ajouter du TLS pour ces communications.

### Port fixe configurable

Les nœuds utilisent des ports dynamiques (`:0`), ce qui complique la configuration du pare-feu (il faut ouvrir une large plage). Permettre aux nœuds de choisir un port fixe via une variable d'environnement (ex: `NODE_PORT=5000`) faciliterait le déploiement.

### Tests automatisés

Mettre en place des tests qui simulent un réseau multi-machines (par exemple avec Docker Compose) pour valider automatiquement le bon fonctionnement du routage en oignon en conditions réseau réelles.

### Rotation dynamique des circuits

Actuellement, la route est fixée au moment de l'envoi. Une amélioration serait de changer automatiquement de route à intervalles réguliers pour renforcer l'anonymat.
