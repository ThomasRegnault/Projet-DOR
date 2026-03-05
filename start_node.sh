#!/bin/bash
N=8
SERVER_ADDR="${SERVER_ADDR:-localhost:8080}"

gnome-terminal -- bash -c "cd node_server/List_Serveur && go run serveur.go; bash" &
sleep 2
for i in $(seq 1 $N); do
  gnome-terminal -- bash -c "cd node_server/node && SERVER_ADDR=$SERVER_ADDR go run main.go node-$i; bash" &
done