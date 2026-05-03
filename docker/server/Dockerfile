FROM alpine:3.14

RUN apk add --no-cache wget tar git

ENV GO_VERSION=1.25.6
ENV NETWORK_PROFILE=default
ENV SERVER_ADDR=host.docker.internal:8080

RUN wget https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz \
    && tar -C /usr/local -xzf go${GO_VERSION}.linux-amd64.tar.gz \
    && rm go${GO_VERSION}.linux-amd64.tar.gz

ENV PATH=$PATH:/usr/local/go/bin

WORKDIR /usr/projet-dor/

ARG CACHEBUST=1

RUN git clone https://github.com/ThomasRegnault/Projet-DOR.git

WORKDIR /usr/projet-dor/Projet-DOR/node_server/List_Serveur/

RUN go get modernc.org/sqlite

RUN go build -o server serveur.go

CMD ["sh", "-c", "./server"]
