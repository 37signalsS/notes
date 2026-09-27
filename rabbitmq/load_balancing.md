# RabbitMQ: Балансировка нагрузки (Load Balancing)

## Определения

- **Load Balancer (Балансировщик):** Устройство или софт, распределяющий входящий трафик между несколькими узлами RabbitMQ для обеспечения отказоустойчивости и балансировки нагрузки.
- **HAProxy:** Высокопроизводительный TCP/HTTP прокси, часто используемый для балансировки AMQP и Management UI трафика.
- **Client-side Load Balancing:** Балансировка на стороне клиента, когда клиент сам выбирает узел для подключения (например, через DNS round-robin).
- **Sticky Sessions:** Режим, при котором клиент始终保持 подключение к одному узлу (не рекомендуется для RabbitMQ).
- **Health Check:** Проверка доступности узлов балансировщиком для исключения нерабочих из пула.

## Архитектура балансировки

```
                    ┌─────────────┐
                    │   Clients   │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │   HAProxy   │
                    │  (L4/L7)    │
                    └──────┬──────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
   ┌──────▼──────┐  ┌──────▼──────┐  ┌──────▼──────┐
   │   RabbitMQ  │  │   RabbitMQ  │  │   RabbitMQ  │
   │   node1     │  │   node2     │  │   node3     │
   └─────────────┘  └─────────────┘  └─────────────┘
```

## Варианты балансировки

### 1. DNS Round-Robin (простейший)

```bash
# /etc/hosts или DNS
rabbitmq1.example.com  A  10.0.0.1
rabbitmq2.example.com  A  10.0.0.2
rabbitmq3.example.com  A  10.0.0.3

# DNS round-robin
rabbitmq-cluster.example.com  A  10.0.0.1
rabbitmq-cluster.example.com  A  10.0.0.2
rabbitmq-cluster.example.com  A  10.0.0.3
```

**Преимущества:** Простота, нет дополнительного софта.
**Недостатки:** Нет health checks, неравномерное распределение.

### 2. HAProxy для AMQP (TCP proxy)

```cfg
# /etc/haproxy/haproxy.cfg

global
    log /dev/log local0
    maxconn 4096

defaults
    log     global
    mode    tcp
    option  tcplog
    timeout connect 5s
    timeout client  120s
    timeout server  120s

# AMQP балансировка
frontend rabbitmq_amqp
    bind *:5672
    default_backend rabbitmq_amqp_backend

backend rabbitmq_amqp_backend
    option tcp-check
    # TCP health check (попытка подключения к порту)
    tcp-check connect port 5672
    
    balance roundrobin
    
    server rabbit1 rabbit1:5672 check inter 5s fall 3 rise 2
    server rabbit2 rabbit2:5672 check inter 5s fall 3 rise 2
    server rabbit3 rabbit3:5672 check inter 5s fall 3 rise 2

# Management UI балансировка
frontend rabbitmq_management
    bind *:15672
    default_backend rabbitmq_mgmt_backend

backend rabbitmq_mgmt_backend
    option httpchk GET /api/health/checks/alarms
    http-check expect status 200
    
    balance roundrobin
    
    server rabbit1 rabbit1:15672 check inter 10s fall 3 rise 2
    server rabbit2 rabbit2:15672 check inter 10s fall 3 rise 2
    server rabbit3 rabbit3:15672 check inter 10s fall 3 rise 2

# Prometheus метрики
frontend rabbitmq_prometheus
    bind *:15692
    default_backend rabbitmq_prom_backend

backend rabbitmq_prom_backend
    option httpchk GET /metrics
    http-check expect status 200
    
    balance roundrobin
    
    server rabbit1 rabbit1:15692 check inter 10s
    server rabbit2 rabbit2:15692 check inter 10s
    server rabbit3 rabbit3:15692 check inter 10s
```

### 3. HAProxy для AMQP с TLS (mTLS)

```cfg
frontend rabbitmq_amqp_tls
    bind *:5671 ssl crt /etc/haproxy/tls/rabbitmq.pem
    mode tcp
    default_backend rabbitmq_amqp_backend

backend rabbitmq_amqp_backend
    mode tcp
    option tcp-check
    tcp-check connect port 5671 ssl
    
    balance roundrobin
    
    server rabbit1 rabbit1:5671 check inter 5s
    server rabbit2 rabbit2:5671 check inter 5s
    server rabbit3 rabbit3:5671 check inter 5s
```

### 4. HAProxy с взвешенным распределением

```cfg
backend rabbitmq_amqp_backend
    balance roundrobin
    
    # Веса для распределения нагрузки
    server rabbit1 rabbit1:5672 check weight 3  # Более мощный
    server rabbit2 rabbit2:5672 check weight 2
    server rabbit3 rabbit3:5672 check weight 1  # Менее мощный
```

### 5. HAProxy с session persistence (sticky)

```cfg
backend rabbitmq_amqp_backend
    balance roundrobin
    
    # Sticky sessions по IP клиента
    stick-table type ip size 200k expire 30m
    stick on src
    
    server rabbit1 rabbit1:5672 check
    server rabbit2 rabbit2:5672 check
    server rabbit3 rabbit3:5672 check
```

**Примечание:** Sticky sessions НЕ рекомендуются для RabbitMQ, так как это снижает балансировку.

### 6. Client-side Load Balancing (Python)

```python
import pika
import random
import socket

class RoundRobinConnection:
    def __init__(self, hosts, port=5672):
        self.hosts = hosts
        self.port = port
        self.current_index = 0
    
    def get_next_host(self):
        host = self.hosts[self.current_index % len(self.hosts)]
        self.current_index += 1
        return host
    
    def create_connection(self):
        for _ in range(len(self.hosts)):
            host = self.get_next_host()
            try:
                # Проверка доступности
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                result = sock.connect_ex((host, self.port))
                sock.close()
                
                if result == 0:
                    return pika.BlockingConnection(
                        pika.ConnectionParameters(host=host, port=self.port)
                    )
            except Exception:
                continue
        
        raise ConnectionError("All hosts are unavailable")

# Использование
hosts = ['rabbit1', 'rabbit2', 'rabbit3']
rr = RoundRobinConnection(hosts)
connection = rr.create_connection()
channel = connection.channel()
```

### 7. Client-side с health checks (Go)

```go
package main

import (
    "net"
    "time"
    amqp "github.com/rabbitmq/amqp091-go"
)

type LoadBalancer struct {
    hosts    []string
    port     int
    healthy  []string
}

func NewLoadBalancer(hosts []string, port int) *LoadBalancer {
    lb := &LoadBalancer{hosts: hosts, port: port}
    go lb.healthCheckLoop()
    return lb
}

func (lb *LoadBalancer) healthCheckLoop() {
    for {
        var healthy []string
        for _, host := range lb.hosts {
            conn, err := net.DialTimeout("tcp", 
                fmt.Sprintf("%s:%d", host, lb.port), 
                2*time.Second)
            if err == nil {
                conn.Close()
                healthy = append(healthy, host)
            }
        }
        lb.healthy = healthy
        time.Sleep(5 * time.Second)
    }
}

func (lb *LoadBalancer) GetConnection() (*amqp.Connection, error) {
    for _, host := range lb.healthy {
        conn, err := amqp.Dial(fmt.Sprintf("amqp://guest:guest@%s:%d/", host, lb.port))
        if err == nil {
            return conn, nil
        }
    }
    return nil, fmt.Errorf("no healthy hosts available")
}
```

### 8. Kubernetes Service (ClusterIP)

```yaml
apiVersion: v1
kind: Service
metadata:
  name: rabbitmq
  namespace: rabbitmq
spec:
  type: ClusterIP
  ports:
    - name: amqp
      port: 5672
      targetPort: 5672
    - name: management
      port: 15672
      targetPort: 15672
    - name: prometheus
      port: 15692
      targetPort: 15692
  selector:
    app: rabbitmq
```

### 9. Kubernetes Ingress (для Management UI)

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: rabbitmq-management
  namespace: rabbitmq
  annotations:
    nginx.ingress.kubernetes.io/ssl-passthrough: "true"
    nginx.ingress.kubernetes.io/backend-protocol: "HTTP"
spec:
  rules:
    - host: rabbitmq.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: rabbitmq-management
                port:
                  number: 15672
  tls:
    - hosts:
        - rabbitmq.example.com
      secretName: rabbitmq-tls
```

## Health Checks

### AMQP Health Check

```bash
# TCP health check
nc -zv rabbit1 5672

# AMQP protocol check
python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(2)
s.connect(('rabbit1', 5672))
s.send(b'AMQP\x00\x00\x09\x01')
response = s.recv(8)
s.close()
print('AMQP OK' if b'AMQP' in response else 'AMQP FAILED')
"
```

### Management API Health Check

```bash
# Общий статус
curl -s -u guest:guest http://rabbit1:15672/api/health/checks/alarms

# Проверка кластера
curl -s -u guest:guest http://rabbit1:15672/api/health/checks/cluster

# Проверка портов
curl -s -u guest:guest http://rabbit1:15672/api/health/checks/listeners
```

## Типичные ошибки

| Ошибка | Причина | Rешение |
|:---|:---|:---|
| Connection refused | Балансировщик не доступен | Проверьте HAProxy конфигурацию и порты |
| Uneven distribution | Sticky sessions включены | Отключите sticky, используйте round-robin |
| Health check failed | Узел недоступен | Проверьте статус RabbitMQ сервиса |
| Split-brain | Неправильный failover | Настройте `cluster_partition_handling` |
| High latency | Длинная цепочка proxy | Используйте L4 балансировку вместо L7 |

## Лучшие практики

1. **Используйте HAProxy** для AMQP — проверенный и надежный вариант.
2. **Настройте health checks** — проверяйте доступность узлов каждые 5-10 секунд.
3. **Используйте round-robin** — без sticky sessions для равномерного распределения.
4. **Балансируйте Management UI** — для доступа изолированно от AMQP.
5. **Используйте TLS** — шифрование трафика через балансировщик.
6. **Мониторьте HAProxy** — метрики через Prometheus exporter.
7. **Тестируйте failover** — остановите узел и проверьте перераспределение.
8. **Для Kubernetes** используйте ClusterIP + Ingress.

## Дополнительная информация

### См. также

- **[Установка и кластеризация](./installation_and_clustering.md)** — топологии кластеров.
- **[Безопасность](./security.md)** — TLS для балансировщика.
- **[Мониторинг и алертинг](./monitoring_and_alerting.md)** — метрики HAProxy.
- **[HAProxy](../WebServers/haproxy_overview.md)** — общий обзор HAProxy.
