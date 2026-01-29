//Cet exemple est identique à l'exemple de Thomas
//a la seule différence qu'il utilise la fonction
//"symétrique" rsa.DecryptOAEP et donc on n'a plus
//besoin d'importer le package "crypto" en plus (on
//utilise juste "crypto/sha256")

package main

import (
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"fmt"
	"os"
)

func main() {
	// Génération d'une clé privée RSA 4096 bits
	privateKey, err := rsa.GenerateKey(rand.Reader, 4096)
	if err != nil {
		fmt.Printf("Error generating RSA key: %s\n", err)
		return
	}
	fmt.Printf("Private: %v\n", privateKey)

	// Générer une clé public à partir de la clé privée
	publicKey := privateKey.PublicKey
	//mt.Printf("Public: %v\n", publicKey)

	// Chiffrer un message avec RSA
	msg := "La terre est plate (info top secrète)"
	fmt.Println("Message à chiffrer:", msg)

	encryptedBytes, err := rsa.EncryptOAEP(sha256.New(), rand.Reader, &publicKey, []byte(msg), nil)
	if err != nil {
		panic(err)
	}

	fmt.Printf("Encrypted message: %s\n", encryptedBytes)

	// Déchiffer un message RSA
	decryptedBytes, err := rsa.DecryptOAEP(sha256.New(), rand.Reader, privateKey, encryptedBytes, nil)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error from decryption: %s\n", err)
	}
	fmt.Println("decrypted message: ", string(decryptedBytes))
}
