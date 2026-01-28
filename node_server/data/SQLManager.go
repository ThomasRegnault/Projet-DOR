package data

import (
	"database/sql"

	_ "github.com/mattn/go-sqlite3"
)

func Connect(path string) (*sql.DB, error) {
	db, err := sql.Open("sqlite3", path)

	if err != nil {
		return nil, err
	}

	defer db.Close()

	return db, nil
}

func InitTable(db *sql.DB) {
	sqlStmt := `
    CREATE TABLE IF NOT EXISTS nodes (
        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
        name TEXT,
		port INTEGER,
		KEY INTEGER
    );
    `
	_, err := db.Exec(sqlStmt)
	if err != nil {
		panic(err)
	}
}

func AddNode(node *Node)
