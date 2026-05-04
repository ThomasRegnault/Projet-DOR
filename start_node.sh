#!/bin/bash
N=5

gnome-terminal -- bash -c "cd node_server/List_Serveur && go run serveur.go; bash" &
sleep 2
for i in $(seq 1 $N); do
  NODE_ID=node1 SERVER_ADDR=localhost:8080 UI_PORT=$((9090 + i))
  gnome-terminal -- bash -c "go run ./node_server/node/ bash" &
done