import os
import sys
import matplotlib.pyplot as plt

def main(log_file):
    if not os.path.exists(log_file):
        print(f"❌ Erreur : Le fichier {log_file} est introuvable.")
        return

    latencies = []
    statuses = {'ACK': 0, 'TIMEOUT': 0, 'DROP': 0}
    
    # 1. Lecture et extraction des données
    with open(log_file, 'r') as f:
        for line in f:
            if line.startswith('RESULT|'):
                parts = line.strip().split('|')
                # Format attendu : RESULT | id | status | latence_ms | retries
# Format réel : RESULT | IP:PORT | STATUS | RETRIES | LATENCE
                if len(parts) >= 5:
                    status = parts[2]
                    
                    if status in statuses:
                        statuses[status] += 1
                    else:
                        statuses[status] = 1
                        
                    if status == 'ACK':
                        try:
                            # On lit parts[4] (la 5ème colonne) au lieu de parts[3] !
                            # On retire 'ms' et 's' au cas où Go change l'unité
                            lat_str = parts[4].replace('ms', '').replace('s', '').strip()
                            lat = float(lat_str)
                            
                            # Si Go a écrit "3.12s" au lieu de "3120ms", on convertit
                            if 's' in parts[4] and 'ms' not in parts[4]:
                                lat *= 1000
                                
                            latencies.append(lat)
                        except ValueError:
                            pass

    # 2. Création du dossier (C'est ça qui manquait dans l'ancien script !)
    output_dir = "dor_graphs"
    os.makedirs(output_dir, exist_ok=True)

    print("📊 Génération des graphiques en cours...")

    # --- GRAPHIQUE 1 : Camembert du taux de livraison ---
    plt.figure(figsize=(8, 6))
    labels = [f"{k} ({v})" for k, v in statuses.items() if v > 0]
    sizes = [v for v in statuses.values() if v > 0]
    colors = ['#4CAF50', '#F44336', '#FF9800'] # Vert pour ACK, Rouge pour Timeout, Orange Drop
    
    plt.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=140)
    plt.title('Taux de livraison des messages (Mininet + Chaos Monkey)')
    plt.savefig(os.path.join(output_dir, '1_taux_livraison.png'))
    plt.close()

    if latencies:
        # --- GRAPHIQUE 2 : Évolution de la latence dans le temps ---
        plt.figure(figsize=(10, 6))
        plt.plot(latencies, marker='o', linestyle='-', color='#2196F3', alpha=0.7)
        plt.title('Évolution de la latence par message')
        plt.xlabel('Numéro du message (Reçu)')
        plt.ylabel('Latence (ms)')
        plt.grid(True, linestyle='--', alpha=0.6)
        plt.savefig(os.path.join(output_dir, '2_evolution_latence.png'))
        plt.close()

        # --- GRAPHIQUE 3 : Histogramme (Répartition des latences) ---
        plt.figure(figsize=(10, 6))
        plt.hist(latencies, bins=15, color='#9C27B0', edgecolor='black', alpha=0.7)
        plt.title('Distribution des latences')
        plt.xlabel('Latence (ms)')
        plt.ylabel('Nombre de messages')
        plt.grid(axis='y', linestyle='--', alpha=0.6)
        
        # Ajout d'une ligne pour la moyenne
        moyenne = sum(latencies) / len(latencies)
        plt.axvline(moyenne, color='red', linestyle='dashed', linewidth=2, label=f'Moyenne : {moyenne:.0f}ms')
        plt.legend()
        
        plt.savefig(os.path.join(output_dir, '3_distribution_latence.png'))
        plt.close()

    print(f"✅ Terminé ! 3 graphiques ont été sauvegardés dans le dossier '{output_dir}/'")

if __name__ == '__main__':
    # Par défaut, va chercher le fichier dans logs_mininet/
    log_path = sys.argv[1] if len(sys.argv) > 1 else 'logs_mininet/results_clean.log'
    main(log_path)