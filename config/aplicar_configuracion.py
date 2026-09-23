#!/usr/bin/env python3
"""Aplica la configuracion completa del laboratorio empresarial.

Idempotente: se puede correr las veces que haga falta. Tras reiniciar los nodos
en GNS3 los contenedores vuelven a su estado de imagen, asi que hay que volver
a ejecutar este script para rearmar VLANs, subinterfaces, DHCP y firewall.

Uso:  python aplicar_configuracion.py
"""
import sys, time, json, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gns3lab as g

PROYECTO = "LAB-EMPRESARIAL"
VLANS = [(10, "10.10.10", "Administracion"),
         (20, "10.10.20", "Ventas"),
         (30, "10.10.30", "IT")]
IPT = "/sbin/iptables-nft"   # el kernel de la GNS3 VM usa backend nf_tables

def descubrir():
    projs = [p for p in g.api('GET', '/v2/projects') if p['name'] == PROYECTO]
    if not projs:
        sys.exit(f"No existe el proyecto {PROYECTO}")
    P = projs[0]['project_id']
    if projs[0]['status'] != 'opened':
        g.api('POST', f'/v2/projects/{P}/open')
        time.sleep(3)
    nodos = g.api('GET', f'/v2/projects/{P}/nodes')
    parados = [n['name'] for n in nodos if n['status'] != 'started']
    if parados:
        print(f"  arrancando nodos detenidos: {', '.join(parados)}")
        g.api('POST', f'/v2/projects/{P}/nodes/start', {}, timeout=600)
        time.sleep(20)
        nodos = g.api('GET', f'/v2/projects/{P}/nodes')
    return P, {n['name']: {'console': n['console'],
                           'aux': n['properties'].get('aux')} for n in nodos}

def cfg_switches(pt):
    plan = {'SW1': {'trunk': ['eth0', 'eth7'], 'acc': {'eth1':10,'eth2':20,'eth3':30}},
            'SW2': {'trunk': ['eth7'],         'acc': {'eth1':10,'eth2':20,'eth3':30}}}
    for sw, p in plan.items():
        cmds = ["ovs-vsctl --if-exists del-br br1",
                "ovs-vsctl --if-exists del-br br2",
                "ovs-vsctl --if-exists del-br br3"]
        for e in ('eth4','eth5','eth6'):
            cmds.append(f"ovs-vsctl --if-exists del-port br0 {e}")
        if sw == 'SW2':
            cmds.append("ovs-vsctl --if-exists del-port br0 eth0")
        for e in p['trunk']:
            cmds.append(f"ovs-vsctl set port {e} vlan_mode=trunk trunks=10,20,30")
        for e, v in p['acc'].items():
            cmds.append(f"ovs-vsctl set port {e} vlan_mode=access tag={v}")
        out = g.sh(pt[sw]['console'], cmds, wait=5)
        errs = [l for l in out.splitlines() if 'ovs-vsctl:' in l]
        print(f"  {sw}: {'OK' if not errs else 'ERRORES ' + str(errs[:2])}")

def cfg_router(pt):
    aux = pt['R1']['aux']
    cmds = ["sysctl -w net.ipv4.ip_forward=1 >/dev/null", "/sbin/ip link set eth1 up"]
    for vid, net, _ in VLANS:
        cmds += [f"/sbin/ip link del eth1.{vid} 2>/dev/null; /sbin/ip link add link eth1 name eth1.{vid} type vlan id {vid}",
                 f"/sbin/ip addr add {net}.1/24 dev eth1.{vid}",
                 f"/sbin/ip link set eth1.{vid} up"]
    # WAN hacia el nodo NAT
    cmds += ["udhcpc -i eth0 -n -q -t 4 -s /usr/share/udhcpc/default.script >/dev/null 2>&1",
             "/sbin/ip -4 -o addr show eth0 | grep -q inet && echo '  WAN OK' || echo '  WAN SIN DIRECCION'"]
    # DHCP por VLAN
    cmds.append("mkdir -p /var/lib/misc /var/run")
    for vid, net, nombre in VLANS:
        cfg = f"/etc/udhcpd-v{vid}.conf"
        lineas = "\n".join([
            f"# DHCP VLAN {vid} - {nombre}", f"interface eth1.{vid}",
            f"start {net}.100", f"end {net}.150", "max_leases 51",
            "opt subnet 255.255.255.0", f"opt router {net}.1",
            "opt dns 8.8.8.8 1.1.1.1", "opt domain lab.local", "opt lease 86400",
            f"lease_file /var/lib/misc/udhcpd-v{vid}.leases",
            f"pidfile /var/run/udhcpd-v{vid}.pid", "auto_time 30"])
        cmds += [f"printf '{lineas}\n' > {cfg}",
                 f"touch /var/lib/misc/udhcpd-v{vid}.leases",
                 f"kill $(cat /var/run/udhcpd-v{vid}.pid 2>/dev/null) 2>/dev/null; udhcpd {cfg}"]
    # NAT + ACL
    cmds += [f"{IPT} -P FORWARD ACCEPT", f"{IPT} -F FORWARD", f"{IPT} -t nat -F POSTROUTING",
             f"{IPT} -t nat -A POSTROUTING -s 10.10.0.0/16 -o eth0 -j MASQUERADE",
             f"{IPT} -A FORWARD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT",
             f"{IPT} -A FORWARD -s 10.10.20.0/24 -d 10.10.30.0/24 -j DROP",
             f"{IPT} -A FORWARD -s 10.10.30.0/24 -d 10.10.20.0/24 -j ACCEPT",
             "echo '  router configurado'",
             "ps aux | grep -c '[u]dhcpd'"]
    out = g.sh(aux, cmds, wait=7)
    for l in out.splitlines():
        if 'WAN' in l or 'router configurado' in l:
            print(l.strip())

def cfg_hosts(pt):
    for pc in ['PC1','PC2','PC3','PC4','PC5','PC6']:
        g.vpcs(pt[pc]['console'], ["ip dhcp"], wait=12)
    time.sleep(2)
    for pc in ['PC1','PC2','PC3','PC4','PC5','PC6']:
        out = g.vpcs(pt[pc]['console'], ["show ip"], wait=7)
        ip = next((l.split(':')[1].strip() for l in out.splitlines() if 'IP/MASK' in l), '??')
        print(f"  {pc}: {ip}")

if __name__ == '__main__':
    print("== Descubriendo proyecto y nodos ==")
    P, pt = descubrir()
    json.dump(pt, open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'ports.json'),'w'), indent=1)
    print(f"  proyecto {P}  |  {len(pt)} nodos")
    print("== Switches: VLANs y troncales ==");  cfg_switches(pt)
    print("== Router: subinterfaces, DHCP, NAT y ACL ==");  cfg_router(pt)
    print("== Hosts: solicitud DHCP ==");  cfg_hosts(pt)
    print("\nConfiguracion aplicada. Para verificar:  python verificar.py")
