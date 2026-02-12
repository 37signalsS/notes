# Практические сценарии SDN

## Сценарий 1: Простой SDN коммутатор

```python
# Mininet + Ryu: создание SDN сети
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.cli import CLI

net = Mininet(controller=RemoteController)
net.addController('c0', ip='127.0.0.1', port=6633)

# Добавление хостов и свитчей
h1 = net.addHost('h1')
h2 = net.addHost('h2')
s1 = net.addSwitch('s1')

# Соединения
net.addLink(h1, s1)
net.addLink(h2, s1)

net.start()
CLI(net)
net.stop()
```

## Сценарий 2: Load Balancer с OpenFlow

```python
# Ryu app: простой L4 load balancer
class LoadBalancer(app_manager.RyuApp):
    virtual_ip = '10.0.0.100'
    servers = ['10.0.0.1', '10.0.0.2', '10.0.0.3']
    
    @set_ev_cls(ofp_event.EventOFPPacketIn)
    def packet_in_handler(self, ev):
        pkt = packet.Packet(ev.msg.data)
        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        
        if ip_pkt and ip_pkt.dst == self.virtual_ip:
            # Выбор сервера (round-robin)
            server = self.select_server()
            
            # Установить flow для forwarding
            self.install_lb_flow(ev.msg.datapath, 
                               ip_pkt.src, server)
```

## Сценарий 3: NetFlow для мониторинга DDoS

```bash
# Обнаружение аномалий с помощью nfdump
nfdump -r nfcapd.current -s srcip/packets \
    -n 20 -o csv | awk -F',' '
    NR>1 {if ($3 > 100000) print $1, $3}'

# Автоматическая блокировка при превышении порога
#!/bin/bash
THRESHOLD=1000000
TOP_TALKERS=$(nfdump -r nfcapd.current -s srcip/bytes -n 5)

while read -r line; do
    BYTES=$(echo $line | awk '{print $NF}')
    IP=$(echo $line | awk '{print $1}')
    
    if [ "$BYTES" -gt "$THRESHOLD" ]; then
        iptables -A INPUT -s $IP -j DROP
        echo "Blocked $IP: $BYTES bytes"
    fi
done <<< "$TOP_TALKERS"
```

## Дополнительная информация

- [Open Networking Foundation (ONF)](https://opennetworking.org/)
- [OpenFlow Specification](https://opennetworking.org/software-defined-standards/specifications/)
- [ONOS Documentation](https://wiki.onosproject.org/)
- [Ryu SDN Framework](https://ryu-sdn.org/)
- [nfdump Documentation](https://github.com/phaag/nfdump)
