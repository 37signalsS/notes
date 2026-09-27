# Disaster Recovery и Backup Traefik: RTO, RPO, failover

## Определения

**RTO (Recovery Time Objective)** — максимальное допустимое время простоя перед восстановлением сервиса.

**RPO (Recovery Point Objective)** — максимальный допустимый объем данных, потерянных при сбое (время с последнего backup).

**Failover** — автоматическое переключение на резервный инстанс при отказе основного.

**Cold standby** — резервный инстанс, который нужно запустить вручную (RTO = время запуска).

**Warm standby** — резервный инстанс, запущенный но не принимающий трафик (RTO = время переключения).

**Hot standby** — активный резервный инстанс за LB (RTO = время detect failover).

**Backup strategy** — план резервного копирования: что, когда, куда.

**Recovery procedure** — пошаговая инструкция восстановления после сбоя.

## Базовые концепции

### Что нужно backup'ить для Traefik

| Компонент | Критичность | Backup |
| :--- | :--- | :--- |
| `acme.json` | **Высокая** | Да, регулярно |
| Статическая конфигурация (`traefik.yml`) | **Высокая** | Да, в Git |
| Динамическая конфигурация (dynamic/*.yml) | **Высокая** | Да, в Git |
| TLS сертификаты (не ACME) | **Средняя** | Да, если используете custom CA |
| Логи | **Низкая** | Опционально, для аудита |
| Плагины | **Средняя** | Да, в Git |

### RTO/RPO для Traefik

| Сценарий | RTO | RPO | Реализация |
| :--- | :--- | :--- | :--- |
| **Один инстанс, ручной restart** | 5-30 мин | 0 | Backup `acme.json`, Git для конфига |
| **HA с keepalived** | 10-30 сек | 0 | Автоматический failover через VIP |
| **K8s с 3+ репликами** | 30-60 сек | 0 | Rolling update, PDB |
| **Multi-region** | 1-5 мин | 0 | Active-active через Global LB |

### Backup strategies

**Full backup (еженедельно):**
```bash
# Конфигурация + сертификаты
tar -czf traefik-backup-$(date +%F).tar.gz \
  /etc/traefik/traefik.yml \
  /etc/traefik/dynamic/ \
  /var/lib/traefik/acme.json
```

**Incremental backup (ежедневно):**
```bash
# Только acme.json (активно меняется)
cp /var/lib/traefik/acme.json /backups/acme.json.$(date +%F)
```

**Off-site backup:**
```bash
# Копирование на удаленный сервер
rsync -avz /backups/traefik/ backup-server:/backups/traefik/
```

### Failover procedures

**Manual failover (bare-metal):**
```bash
# 1. Остановить Traefik наPrimary
sudo systemctl stop traefik

# 2. Запустить наSecondary
sudo systemctl start traefik

# 3. Переключить VIP (если keepalived не работает)
sudo ip addr add 192.168.1.100/32 dev eth0
```

**Automatic failover (K8s):**
- Rolling update: автоматически
- Node drain: PodDisruptionBudget + deployment replicas
- Zone failure: cluster-autoscaler + topology spread constraints

## Практические сценарии

### Сценарий 1: Полный backup и восстановление

```bash
# Backup
TRAEFIK_BACKUP_DIR="/backups/traefik/$(date +%F)"
mkdir -p "$TRAEFIK_BACKUP_DIR"

# 1. Статическая конфигурация
sudo cp -a /etc/traefik/traefik.yml "$TRAEFIK_BACKUP_DIR/"

# 2. Динамическая конфигурация
sudo cp -a /etc/traefik/dynamic "$TRAEFIK_BACKUP_DIR/"

# 3. Сертификаты
sudo cp -a /var/lib/traefik/acme.json "$TRAEFIK_BACKUP_DIR/"

# 4. Права
sudo chown -R traefik:traefik "$TRAEFIK_BACKUP_DIR"
sudo chmod 600 "$TRAEFIK_BACKUP_DIR/acme.json"

# Восстановление после полной потери ноды
sudo systemctl stop traefik
sudo cp "$TRAEFIK_BACKUP_DIR/traefik.yml" /etc/traefik/
sudo cp -a "$TRAEFIK_BACKUP_DIR/dynamic" /etc/traefik/
sudo cp "$TRAEFIK_BACKUP_DIR/acme.json" /var/lib/traefik/
sudo chown -R traefik:traefik /etc/traefik /var/lib/traefik
sudo chmod 600 /var/lib/traefik/acme.json
sudo systemctl start traefik
```

### Сценарий 2: Keepalived failover (bare-metal)

```bash
# /etc/keepalived/keepalived.conf
vrrp_instance VI_1 {
  state MASTER
  interface eth0
  virtual_router_id 51
  priority 100
  advert_int 1
  authentication {
    auth_type PASS
    auth_pass secret
  }
  virtual_ipaddress {
    192.168.1.100/24
  }
  track_script {
    check_traefik
  }
}

vrrp_script check_traefik {
  script "/usr/local/bin/check_traefik.sh"
  interval 2
  weight -20
  fall 2
  rise 2
}
```

`check_traefik.sh`:
```bash
#!/bin/bash
if curl -sf http://127.0.0.1:8080/ping > /dev/null; then
  exit 0
else
  exit 1
fi
```

### Сценарий 3: K8s failover с PDB

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: traefik
  namespace: traefik
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: traefik
```

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: traefik
  namespace: traefik
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
```

### Сценарий 4: Multi-region failover

```
Region A (active):          Region B (standby):
┌─────────────────┐         ┌─────────────────┐
│ Traefik LB      │         │ Traefik LB      │
│ ┌─────────────┐ │         │ ┌─────────────┐ │
│ │ Traefik 1   │ │         │ │ Traefik 1   │ │
│ │ Traefik 2   │ │         │ │ Traefik 2   │ │
│ └─────────────┘ │         │ └─────────────┘ │
└────────┬────────┘         └────────┬────────┘
         │                          │
         └──────────┬───────────────┘
                    │ DNS failover (Route53, CloudFlare)
                    ▼
              Global Load Balancer
```

Failover:
1. Detect failure (health check)
2. Update DNS TTL to 60s ( beforehand!)
3. Switch DNS to Region B
4. Verify `/ping` на Region B

### Сценарий 5: DR drill (ежеквартально)

```bash
#!/bin/bash
# dr-drill.sh

echo "=== DR Drill Started ==="

# 1. Backup current state
echo "Backing up..."
tar -czf /tmp/traefik-drill-backup.tar.gz /etc/traefik/ /var/lib/traefik/

# 2. Stop Traefik
echo "Stopping Traefik..."
sudo systemctl stop traefik

# 3. Simulate data loss
echo "Simulating data loss..."
sudo rm -f /var/lib/traefik/acme.json
sudo rm -rf /etc/traefik/dynamic/*

# 4. Restore from backup
echo "Restoring..."
sudo cp /tmp/traefik-drill-backup.tar.gz /tmp/
sudo tar -xzf /tmp/traefik-drill-backup.tar.gz -C /
sudo chown -R traefik:traefik /etc/traefik /var/lib/traefik
sudo chmod 600 /var/lib/traefik/acme.json

# 5. Start Traefik
echo "Starting Traefik..."
sudo systemctl start traefik

# 6. Verify
sleep 10
curl -s http://localhost:8080/ping
# → OK

echo "=== DR Drill Completed ==="
```

### Сценарий 6: ACME certificates при DR

Если Traefik восстановлен из backup, но certificates expired:
1. Traefik попытается renew (если > 30 дней до expire — auto)
2. Если < 30 days — manual intervention:
   - Временно используйте staging CA
   - Или manual certificate issuance
   - Или external cert-manager

## Операции и команды

```bash
# Проверка срока certificates
curl -s https://app.example.com | openssl s_client -connect app.example.com:443 -servername app.example.com 2>/dev/null | openssl x509 -noout -dates
# → notAfter=...

# Проверка acme.json
sudo ls -la /var/lib/traefik/acme.json
sudo chown traefik:traefik /var/lib/traefik/acme.json
sudo chmod 600 /var/lib/traefik/acme.json

# Проверка failover (keepalived)
keepalived -D  # debug mode
sudo systemctl status keepalived

# Проверка K8s failover
kubectl get pods -n traefik -o wide
kubectl describe node <node-name> | grep -i taint

# Проверка DNS failover
dig app.example.com
# → 192.168.1.100 (VIP)
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **acme.json corrupted** | SIGKILL во время записи, duplicate instances | Восстановите из backup, перевыпустите certificates |
| **Certificates expired** | Traefik был остановлен > 30 дней | Manual issuance или staging CA |
| **Failover не работает** | Keepalived split-brain, PDB блокирует | Проверьте unicast, PDB minAvailable |
| **DNS не обновляется** | TTL слишком высокий | Установите TTL 60s beforehand |
| **DR drill падает** | Восстановление неполное, права неверные | Проверьте chown/chmod, конфигурацию |
| **RTO превышен** | Ручной failover, нет automation | Внедрите keepalived/K8s/Global LB |

## Рекомендации

- RTO: автоматический failover (keepalived/K8s) = 30-60 сек; ручной = 5-30 мин
- RPO: 0 (continuous replication) или < 1 день (ежедневный backup)
- Backup `acme.json`: ежедневно, off-site
- Конфигурация: в Git, автоматический deploy
- Failover: тестируйте раз в квартал (DR drill)
- DNS TTL: 60s для быстрого failover
- ACME: используйте staging для тестов, production для production
- Документируйте recovery procedure в runbook

## Дополнительная информация

- [Traefik на bare-metal](./traefik-bare-metal.md) — systemd, backup acme.json
- [High Availability Traefik](./traefik-high-availability.md) — keepalived, rolling update
- [Traefik в Kubernetes](./traefik-kubernetes.md) — PDB, deployment, probes
- [Мониторинг сертификатов](./traefik-cert-monitoring.md) — expiration alerts
