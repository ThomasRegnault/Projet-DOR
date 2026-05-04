#!/bin/bash
i=${1:-1} NODE_ID="node${i}" WEB_PORT="909${i}" SERVER_ADDR=localhost:8080 go run ./node_server/node/ 
