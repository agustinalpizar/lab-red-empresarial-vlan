# Laboratorio de Red Empresarial — VLANs, Inter-VLAN Routing, DHCP y ACLs

Laboratorio de red empresarial funcional montado en **GNS3** sobre la GNS3 VM, con enrutamiento inter-VLAN por *router-on-a-stick*, DHCP por VLAN, salida a internet por NAT y un firewall con política asimétrica entre departamentos.

Toda la evidencia de la carpeta `evidencia/` es **salida real** de los equipos del laboratorio, capturada por consola. No hay salidas simuladas ni escritas a mano.

## Sobre la implementación

Los conceptos de red son los estándar — VLANs 802.1Q, router-on-a-stick, ámbitos DHCP por segmento, filtrado con estado — pero conviene decir desde el arranque con qué herramientas están implementados:

- **Los switches son Open vSwitch**, no switches Cisco. La configuración y la evidencia de VLANs usan `ovs-vsctl`, no `show vlan brief`.
- **El firewall es `iptables-nft`** (backend nftables del kernel Linux), no una ACL con sintaxis Cisco IOS.

Ambas son herramientas reales de producción: Open vSwitch es el switch virtual que mueve tráfico en buena parte de las nubes actuales, y nftables es el firewall del kernel Linux. La diferencia con un laboratorio hecho en Cisco IOS no está en el rigor de la implementación ni en lo que se verifica, sino en la sintaxis de los comandos. Si venís buscando específicamente sintaxis Cisco, este repositorio no la tiene; si lo que te interesa es el diseño de la red y su verificación, el plan de direccionamiento, la política de firewall y la matriz de pruebas se trasladan a cualquier plataforma.

---

## Topología

```
                        ( Internet )
                             |
                      [ NAT1 ]  nodo NAT de GNS3
                             |
                             |  eth0 -- 192.168.42.57/24 (DHCP)
                    +---------------------+
                    |   R1   FRR 9.1.0    |   router-on-a-stick
                    | eth1.10  10.10.10.1 |
                    | eth1.20  10.10.20.1 |
                    | eth1.30  10.10.30.1 |
                    +---------------------+
                             |  eth1 ---- TRUNK 802.1Q (VLANs 10,20,30)
                             |
                      [ SW1 ] Open vSwitch 2.17.12
                       |  |  |
                       |  |  |   eth7 --- TRUNK 802.1Q --- eth7
                       |  |  |                              |
                     PC1 PC2 PC3                     [ SW2 ] Open vSwitch
                     v10 v20 v30                       |   |   |
                                                     PC4 PC5 PC6
                                                     v10 v20 v30
```

Cada VLAN tiene un host en **cada** switch, de modo que todo ping intra-VLAN atraviesa el enlace troncal SW1–SW2 y demuestra que el trunk transporta las tres VLANs etiquetadas.

## Plan de direccionamiento

| VLAN | Departamento    | Red             | Gateway      | Pool DHCP                     |
|-----:|-----------------|-----------------|--------------|-------------------------------|
|   10 | Administración  | 10.10.10.0/24   | 10.10.10.1   | 10.10.10.100 – 10.10.10.150   |
|   20 | Ventas          | 10.10.20.0/24   | 10.10.20.1   | 10.10.20.100 – 10.10.20.150   |
|   30 | IT              | 10.10.30.0/24   | 10.10.30.1   | 10.10.30.100 – 10.10.30.150   |

Direcciones entregadas por DHCP:

| Host | VLAN | Switch | Dirección      | MAC                 |
|------|-----:|--------|----------------|---------------------|
| PC1  |   10 | SW1    | 10.10.10.102   | 00:50:79:66:68:00   |
| PC2  |   20 | SW1    | 10.10.20.103   | 00:50:79:66:68:01   |
| PC3  |   30 | SW1    | 10.10.30.104   | 00:50:79:66:68:02   |
| PC4  |   10 | SW2    | 10.10.10.105   | 00:50:79:66:68:03   |
| PC5  |   20 | SW2    | 10.10.20.106   | 00:50:79:66:68:04   |
| PC6  |   30 | SW2    | 10.10.30.107   | 00:50:79:66:68:05   |

## Asignación de puertos

| Switch | Puerto | Modo   | VLAN / VLANs permitidas | Conectado a |
|--------|--------|--------|-------------------------|-------------|
| SW1    | eth0   | trunk  | 10, 20, 30              | R1 eth1     |
| SW1    | eth1   | access | 10                      | PC1         |
| SW1    | eth2   | access | 20                      | PC2         |
| SW1    | eth3   | access | 30                      | PC3         |
| SW1    | eth7   | trunk  | 10, 20, 30              | SW2 eth7    |
| SW2    | eth1   | access | 10                      | PC4         |
| SW2    | eth2   | access | 20                      | PC5         |
| SW2    | eth3   | access | 30                      | PC6         |
| SW2    | eth7   | trunk  | 10, 20, 30              | SW1 eth7    |

## Política de firewall

| Origen           | Destino          | Política  | Regla |
|------------------|------------------|-----------|-------|
| Ventas (20)      | IT (30)          | BLOQUEADO | `-s 10.10.20.0/24 -d 10.10.30.0/24 -j DROP` |
| IT (30)          | Ventas (20)      | PERMITIDO | `-s 10.10.30.0/24 -d 10.10.20.0/24 -j ACCEPT` |
| Administración   | cualquiera       | PERMITIDO | política por defecto ACCEPT |
| 10.10.0.0/16     | Internet         | PERMITIDO | `MASQUERADE` de salida por eth0 |

La asimetría se logra con seguimiento de conexiones: la primera regla acepta `ESTABLISHED,RELATED`, de modo que las **respuestas** de un ping iniciado desde IT hacia Ventas vuelven sin que las bloquee la regla `DROP`, mientras que un ping **iniciado** desde Ventas hacia IT nunca crea estado y se descarta.

```
iptables-nft -A FORWARD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables-nft -A FORWARD -s 10.10.20.0/24 -d 10.10.30.0/24 -j DROP
iptables-nft -A FORWARD -s 10.10.30.0/24 -d 10.10.20.0/24 -j ACCEPT
```

## Resultados de verificación

16 pruebas de ping, **16 con el resultado esperado**:

| Prueba | Esperado | Obtenido |
|--------|----------|----------|
| Cada host a su gateway (6 pruebas)               | pasa    | pasa 3/3 |
| Intra-VLAN cruzando el trunk SW1–SW2 (3 pruebas) | pasa    | pasa 3/3 |
| Inter-VLAN Administración hacia Ventas e IT      | pasa    | pasa 3/3 |
| Ventas hacia IT, mismo switch                    | bloquea | 0/3      |
| Ventas hacia IT, entre switches                  | bloquea | 0/3      |
| IT hacia Ventas, mismo switch                    | pasa    | pasa 3/3 |
| IT hacia Ventas, entre switches                  | pasa    | pasa 3/3 |
| Host a internet (1.1.1.1) por NAT                | pasa    | pasa 3/3 |

Los contadores del firewall confirman de forma independiente que la política se aplicó sobre tráfico real: 6 paquetes descartados en la regla Ventas→IT y 6 aceptados en la regla IT→Ventas, exactamente los dos ensayos de 3 pings cada uno.

## Evidencia

Capturas incluidas en este repositorio:

| Archivo | Contenido |
|---------|-----------|
| `evidencia/04-firewall-acl.txt` | Reglas del firewall con contadores de paquetes y ruleset completo |
| `evidencia/06-pruebas-ping-acl.txt` | Matriz de 16 pruebas de ping con la salida completa de cada una |

Son las dos capturas que sostienen la parte menos obvia del laboratorio: la política asimétrica entre VLANs y su verificación. El laboratorio genera además capturas de las VLANs en cada switch, de las subinterfaces y la tabla de ruteo del router, de los ámbitos DHCP con sus concesiones y del direccionamiento de los seis hosts, todas reproducibles desde los equipos con el laboratorio en marcha.

## Componentes

| Rol | Implementación | Por qué |
|-----|----------------|---------|
| Router | contenedor **FRR 9.1.0** (`quay.io/frrouting/frr:9.1.0`) | subinterfaces 802.1Q del kernel, `zebra` para la vista de ruteo, `iptables-nft` para el firewall y `udhcpd` para DHCP |
| Switches | contenedores **Open vSwitch 2.17.12** (`gns3/openvswitch:latest`) | switch con VLANs real y CLI propia (`ovs-vsctl`), a diferencia del switch interno de GNS3 que no expone comandos `show` |
| Hosts | **VPCS** (nodo interno de GNS3) | cliente DHCP y ping, consumo mínimo de recursos |
| Internet | **nodo NAT** de GNS3 | salida simulada; el router obtiene 192.168.42.57/24 por DHCP |

## Cómo reproducirlo

Requiere la GNS3 VM corriendo y el proyecto `LAB-EMPRESARIAL` en el controlador.

```bash
cd config
python aplicar_configuracion.py
```

`aplicar_configuracion.py` descubre el proyecto por la API del controlador, arranca los nodos que estén detenidos y aplica la configuración completa: VLANs y troncales en los switches, subinterfaces 802.1Q y gateways en el router, los tres ámbitos DHCP, el NAT de salida y las reglas de firewall. Usa `gns3lab.py`, que habla con la API REST del controlador y con las consolas telnet de los nodos.

El script de configuración es idempotente y se puede correr cuantas veces sea necesario. Se validó deteniendo y rearrancando los 10 nodos: rearmó VLANs, subinterfaces, DHCP y firewall desde cero, los 6 hosts recibieron las mismas direcciones y las 16 pruebas volvieron a dar el resultado esperado.

### Nota sobre persistencia

Los contenedores de GNS3 vuelven al estado de su imagen al reiniciarse: en esta plataforma el único directorio persistente es `/etc/network`. Por eso la configuración vive en `aplicar_configuracion.py` y no dentro de los nodos, que es además la forma en que conviene versionar un laboratorio.

## Estructura del repositorio

```
.
├── README.md
├── config/
│   ├── aplicar_configuracion.py    configuración completa del laboratorio, idempotente
│   └── gns3lab.py                  API REST del controlador GNS3 y consolas telnet
└── evidencia/
    ├── 04-firewall-acl.txt         reglas con contadores de paquetes
    └── 06-pruebas-ping-acl.txt     matriz de 16 pruebas de ping
```

`config/aplicar_configuracion.py` no lleva credenciales dentro: lee el usuario y la contraseña del controlador GNS3 desde `gns3_server.ini` de la instalación local en tiempo de ejecución.

## Licencia

[MIT](LICENSE) © 2026 Agustín Alpízar Hernández.
