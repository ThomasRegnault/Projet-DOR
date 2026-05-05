#!/usr/bin/env python3
import time
import random
import threading
import os
from mininet.net import Mininet
from mininet.node import OVSBridge
from mininet.link import TCLink
from mininet.log import setLogLevel, info

# --- CONFIGURATION DU TEST ---
NB_RELAIS = 10
NB_MESSAGES = 300
MAX_RETRIES = 3
CHAOS_INTERVAL = 3  
CHAOS_DURATION = 5  

def chaos_monkey(net, running_event):
    """Coupe et rétablit aléatoirement les liens réseau des relais"""
    time.sleep(10)
    info("\n[!] Début du Chaos Monkey (Coupures réseau aléatoires)...\n")
    
    while running_event.is_set():
        target = f'h{random.randint(1, NB_RELAIS)}'
        
        info(f"\n[X] Coupure du lien de {target}")
        net.configLinkStatus(target, 's1', 'down')
        
        time.sleep(CHAOS_DURATION)
        
        info(f"\n[V] Rétablissement du lien de {target}")
        net.configLinkStatus(target, 's1', 'up')
        
        time.sleep(CHAOS_INTERVAL)

def run_benchmark():
    os.system("rm -f logs_mininet/*.log")
    os.system("mkdir -p logs_mininet")

    net = Mininet(switch=OVSBridge, link=TCLink, controller=None)
    s1 = net.addSwitch('s1')

    info("*** Création des noeuds virtuels...\n")
    h_server = net.addHost('h_server', ip='10.0.0.254')
    h_recv = net.addHost('h_recv', ip='10.0.0.100')
    h_send = net.addHost('h_send', ip='10.0.0.200')
    
    net.addLink(h_server, s1, delay='5ms')
    net.addLink(h_recv, s1, delay='20ms')
    net.addLink(h_send, s1, delay='20ms')

    relais_hosts = []
    for i in range(1, NB_RELAIS + 1):
        h = net.addHost(f'h{i}', ip=f'10.0.0.{i}')
        relais_hosts.append(h)
        latence = f"{random.randint(10, 100)}ms"
        net.addLink(h, s1, delay=latence, loss=1) 

    info("*** Démarrage du réseau...\n")
    net.start()

    # 1. Lancer le serveur (avec sleep infinity pour garder l'entrée ouverte)
    info("*** Démarrage du Serveur...\n")
    h_server.cmd('cd ../List_Serveur && sleep infinity | ./serveur_bin > ../tests/logs_mininet/server.log 2>&1 &')
    time.sleep(2)

    # 2. Lancer le Receiver
    info("*** Démarrage du Receiver...\n")
    h_recv.cmd('cd ../node && sleep infinity | PORT=9000 SERVER_ADDR=10.0.0.254:8080 ./node_bin receiver_node > ../tests/logs_mininet/recv.log 2>&1 &')
    time.sleep(2)

    # 3. Lancer les Relais
    info(f"*** Démarrage de {NB_RELAIS} relais avec latences variables...\n")
    for i, h in enumerate(relais_hosts):
        port = 9000 + i
        h.cmd(f'cd ../node && sleep infinity | SERVER_ADDR=10.0.0.254:8080 ./node_bin relay_{i} {port} > ../tests/logs_mininet/relay_{i}.log 2>&1 &')
    time.sleep(5)

    # 4. Lancer le Chaos Monkey
    running_event = threading.Event()
    running_event.set()
    chaos_thread = threading.Thread(target=chaos_monkey, args=(net, running_event))
    chaos_thread.start()

    # 5. Lancer le test depuis le Sender
    info(f"\n*** Lancement du BENCHMARK ({NB_MESSAGES} messages) depuis h_send...\n")
    bench_cmd = f"BENCH:{NB_MESSAGES}:3:{MAX_RETRIES}:10.0.0.100:9000"
    
    # On fait un echo de la commande PUIS un sleep infinity pour ne pas couper le process Sender
    h_send.cmd(f'cd ../node && (sleep 2; echo "{bench_cmd}"; sleep infinity) | SERVER_ADDR=10.0.0.254:8080 ./node_bin sender_node 8888 > ../tests/logs_mininet/sender_bench.log 2>&1 &')
    info("*** Attente des résultats (environ 45 secondes)...\n")
    time.sleep(45)

    info("*** Fin du test, arrêt du réseau...\n")
    running_event.clear()
    chaos_thread.join()
    
    # Extraire les logs localement
    os.system("grep 'RESULT|' logs_mininet/sender_bench.log > logs_mininet/results_clean.log")
    
    net.stop()

    info("\n" + "="*50 + "\n")
    info("              BILAN DU BENCHMARK\n")
    info("="*50 + "\n")
    os.system("python3 analyze_bench.py logs_mininet/results_clean.log")

if __name__ == '__main__':
    setLogLevel('info')
    run_benchmark()