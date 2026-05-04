# Benchmark DOR avec Mininet

Ce dossier contient un banc de test complet utilisant Mininet pour simuler un réseau avec de vrais délais, des pertes de paquets, et un "Chaos Monkey" (déconnexion aléatoire des nœuds).

Attention : il faut que le code du serveur et des noeuds soient compilés avant !

## 🛠️ Prérequis
Ce script nécessite un environnement Linux (natif ou WSL2) et l'outil réseau Mininet.
*Important : N'installez PAS mininet via `pip`. C'est un paquet système.*
```bash
sudo apt-get update
sudo apt-get install mininet openvswitch-switch


