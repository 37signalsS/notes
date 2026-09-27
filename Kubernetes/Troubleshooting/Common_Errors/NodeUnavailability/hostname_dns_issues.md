# Недоступность узла: Проблемы hostname и DNS

Некорректная настройка hostname, FQDN и `/etc/hosts` на узлах Kubernetes приводит к невозможности регистрации узла в кластере, ошибкам TLS, проблемам с DNS-резолвом и некорректной работе kubelet. Эти ошибки маскируются как сетевые проблемы или проблемы с сертификатами.

## Основные определения

**Hostname** — имя узла, возвращаемое командой `hostname`. В Kubernetes используется для идентификации узла в объекте Node (`metadata.name`). kubelet получает его через `--hostname-override` или системный вызов `os.Hostname()`.

**FQDN (Fully Qualified Domain Name)** — полное доменное имя узла (например, `node-1.dc1.lab.local`). Используется для DNS-резолва и корректной работы TLS-сертификатов. В Kubernetes FQDN критичен для StatefulSet подов (DNS A-записи).

**/etc/hosts** — локальный файл маппинга IP → hostname. Используется для резолва hostname до DNS. При неправильной настройке kubelet может резолвить hostname в неверный IP-адрес.

**DNS A/AAAA Record** — запись домена → IP-адрес. В Kubernetes CoreDNS предоставляет A-записи для Service (`<svc>.<ns>.svc.cluster.local`) и подов StatefulSet.

**Reverse DNS (PTR)** — обратная запись IP → hostname. Используется для аутентификации TLS и логирования. kubelet может требовать PTR-запись для обратного резолва.

## Основные концепции

### Как hostname влияет на Kubernetes

| Компонент | Использование hostname | Последствие ошибки |
| :--- | :--- | :--- |
| **kubelet** | Регистрация узла в API (`--hostname-override`) | Узел не регистрируется, `NotReady` |
| **Node object** | `metadata.name` = hostname | Конфликт имён, дублирование узлов |
| **TLS证书** | SAN (Subject Alternative Name) содержит hostname | `x509: certificate is valid for...` |
| **Pod DNS** | `<pod-ip>.<namespace>.pod.cluster.local` | DNS-резолв не работает |
| **StatefulSet** | `<pod-name>.<headless-svc>.<ns>.svc.cluster.local` | Headless Service не резолвит |
| **etcd** | Member URLs содержат hostname | etcd cluster не формируется |

### Типичные проблемы hostname

| Проблема | Симптом | Типичная причина |
| :--- | :--- | :--- |
| DHCP hostname | Имя меняется при перезагрузке | DHCP выдаёт hostname |
| Duplicate hostname | `node already exists in cluster` | Два узла с одинаковым именем |
| Short vs FQDN | TLS证书 не проходит проверку | SAN содержит short, а запрос идёт по FQDN |
| hostname с Caps | kubelet crash с panic | Недопустимые символы в hostname |
| Точка в hostname | `Invalid value` в Node object | hostname содержит `.` (точку) |

## Практические сценарии

### Сценарий 1: Kubelet не запускается из-за hostname

**Симптом**: kubelet падает с ошибкой `Failed to determine a valid hostname` или `unable to resolve`. Узел не регистрируется в кластере.

**Диагностика:**
```bash
# 1. Проверка текущего hostname
hostname
# → node-1

# 2. Проверка FQDN
hostname -f
# → node-1   ← НЕТ FQDN, только short hostname

# 3. Проверка /etc/hosts
cat /etc/hosts | grep $(hostname)
# → 127.0.0.1   localhost
# → 10.0.1.10   node-1   ← нет FQDN-записи

# 4. Проверка резолва hostname
getent hosts $(hostname)
# → 10.0.1.10   node-1   ← resolves к IP

# 5. Проверка hostname в kubelet
ps aux | grep kubelet | grep hostname
# → kubelet --hostname-override=node-1

# 6. Проверка логов kubelet
journalctl -u kubelet -n 50 --no-pager | grep -i "hostname\|name"
# → E0904 17:35:00 kubelet.go:2341] Failed to register node:
# →   node "node-1" already exists in cluster
```

**Решение:**
```bash
# 1. Установить hostnamectl
sudo hostnamectl set-hostname node-1.lab.local

# 2. Добавить FQDN в /etc/hosts
echo "10.0.1.10   node-1.lab.local node-1" | sudo tee -a /etc/hosts

# 3. Проверка
hostname -f
# → node-1.lab.local

# 4. Перезапустить kubelet
sudo systemctl restart kubelet
```

---

### Сценарий 2: Дублирование hostname в кластере

**Симптом**: После перезагрузки появляется второй узел с тем же именем. `kubectl get nodes` показывает два узла с одним `NAME`, но разными `UID`.

**Диагностика:**
```bash
# 1. Проверка узлов с одинаковым hostname
kubectl get nodes -o custom-columns=NAME:.metadata.name,UID:.metadata.uid,IP:.status.addresses[?(@.type=="InternalIP")].address
# → NAME    UID                                    IP
# → node-1  a1b2c3d4-e5f6-7890-abcd-ef1234567890   10.0.1.10
# → node-1  f0e1d2c3-b4a5-6789-0fed-cba987654321   10.0.1.11   ← старый узел!

# 2. Проверка Lease для hostname
kubectl get lease -n kube-node-lease node-1 -o yaml
# → spec:
# →   holderIdentity: node-1
# →   renewTime: "2026-09-04T17:30:00Z"

# 3. Проверка events
kubectl get events --field-selector involvedObject.name=node-1 | grep -i "register\|duplicat"
# → Warning  NodeDuplicate  node-1  node "node-1" already exists, but UUID differs

# 4. Проверка, какой узел активен
kubectl get node node-1 -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'
# → True   ← только один должен быть Ready
```

**Решение:**
```bash
# 1. Удалить старый (мёртвый) узел
kubectl delete node node-1 --cascade=foreground

# 2. Если старый узел всё ещё жив — выключить kubelet на нём
ssh old-node-1 "sudo systemctl stop kubelet"

# 3. Предотвращение: настроить уникальный hostname через cloud-init или DHCP
# cloud-init:
# hostname: node-1.lab.local
# manage_etc_hosts: true

# 4. Проверка
kubectl get nodes
# → NAME    STATUS   ROLES    AGE   VERSION
# → node-1  Ready    worker   30d   v1.31.0
```

---

### Сценарий 3: TLS certificate hostname mismatch

**Симптом**: Kubelet или API-сервер отклоняют TLS-соединение. Ошибка: `x509: certificate is valid for <name1>, <name2>, not <name3>`.

**Диагностика:**
```bash
# 1. Проверка SAN в сертификате kubelet
openssl x509 -in /var/lib/kubelet/pki/kubelet-server-current.pem -text -noout | grep -A 5 "Subject Alternative Name"
# → X509v3 Subject Alternative Name:
# →     DNS:node-1, DNS:node-1.lab.local, IP Address:10.0.1.10

# 2. Проверка, с каким именем подключается клиент
openssl s_client -connect node-1:10250 -servername node-1.lab.local 2>/dev/null | openssl x509 -noout -subject
# → subject=CN = kubelet   ← имя не совпадает

# 3. Проверка TLS-ошибок в логах kubelet
journalctl -u kubelet -n 50 --no-pager | grep -i "tls\|x509\|certificate"
# → x509: certificate is valid for node-1, not node-1.lab.local

# 4. Проверка hostname, который использует kubelet
cat /var/lib/kubelet/config.yaml | grep hostname
# → hostnameOverride: node-1.lab.local   ← а SAN содержит node-1
```

**Решение:**
```bash
# 1. Пересоздать сертификаты с правильными SAN
# Остановить kubelet
sudo systemctl stop kubelet

# Удалить старые сертификаты
sudo rm -f /var/lib/kubelet/pki/*

# Запустить kubelet для генерации нового CSR
sudo systemctl start kubelet

# Одобрить CSR
kubectl certificate approve $(kubectl get csr -o name | grep node-1)

# 2. Проверка нового сертификата
openssl x509 -in /var/lib/kubelet/pki/kubelet-server-current.pem -text -noout | grep -A 5 "Subject Alternative Name"
# → DNS:node-1, DNS:node-1.lab.local, IP Address:10.0.1.10

# 3. Настроить hostname-override в kubelet
# В /var/lib/kubelet/config.yaml:
# hostnameOverride: node-1.lab.local
```

---

### Сценарий 4: DNS-резолв не работает на узле

**Симптом**: kubelet не может разрешить имя API-сервера. `curl https://kubernetes.default.svc.cluster.local` возвращает `Could not resolve hostname`. Узел в `Unknown`.

**Диагностика:**
```bash
# 1. Проверка DNS-сервера на узле
cat /etc/resolv.conf
# → nameserver 10.233.0.10
# → search default.svc.cluster.local svc.cluster.local cluster.local
# → ndots 5

# 2. Проверка резолва
nslookup kubernetes.default.svc.cluster.local
# → server can't find kubernetes.default.svc.cluster.local: NXDOMAIN

# 3. Проверка, доступен ли CoreDNS
kubectl get pods -n kube-system -l k8s-app=kube-dns -o wide
# → coredns-abc12  0/1   CrashLoopBackOff  5  10m   ← CoreDNS упал

# 4. Проверка DNS из пода
kubectl run dns-test --image=busybox:1.36 --rm -it --restart=Never -- nslookup kubernetes.default
# → Server:    10.233.0.10
# → Name:      kubernetes.default.svc.cluster.local
# → Address:   10.233.0.1

# 5. Проверка DNS через TCP (вдруг UDP заблокирован)
kubectl exec dns-test -- nslookup -vc kubernetes.default
```

**Решение:**
```bash
# 1. Если CoreDNS упал — перезапустить
kubectl rollout restart deployment coredns -n kube-system
kubectl rollout status deployment coredns -n kube-system

# 2. Если DNS не работает на узле — исправить /etc/resolv.conf
echo "nameserver 10.233.0.10" | sudo tee /etc/resolv.conf
echo "search default.svc.cluster.local svc.cluster.local cluster.local" | sudo tee -a /etc/resolv.conf
echo "ndots 5" | sudo tee -a /etc/resolv.conf

# 3. Проверка, что DNS работает из kubelet
nslookup kubernetes.default.svc.cluster.local 10.233.0.10
# → Name:      kubernetes.default.svc.cluster.local
# → Address:   10.233.0.1
```

---

### Сценарий 5: StatefulSet DNS не резолвит

**Симптом**: Под StatefulSet не может разрешить hostname другого пода в том же StatefulSet. `ping my-pod-0.my-headless-svc.default.svc.cluster.local` не работает.

**Диагностика:**
```bash
# 1. Проверка headless Service
kubectl get svc my-headless-svc -o yaml | grep clusterIP
# → clusterIP: None   ← headless, правильно

# 2. Проверка DNS-записи
kubectl run dns-test --image=busybox:1.36 --rm -it --restart=Never -- nslookup my-pod-0.my-headless-svc.default.svc.cluster.local
# → ** server can't find my-pod-0.my-headless-svc.default.svc.cluster.local: NXDOMAIN

# 3. Проверка, что поды StatefulSet существуют
kubectl get pods -l app=my-app
# → NAME        READY   STATUS    RESTARTS   AGE
# → my-pod-0    1/1     Running   0          5m
# → my-pod-1    1/1     Running   0          3m

# 4. Проверка EndpointSlice для headless Service
kubectl get endpointslice -n default -l kubernetes.io/service-name=my-headless-svc
# → NAME                    ENDPOINTS                                       AGE
# → my-headless-svc-abc12   10.244.1.5,10.244.2.8                           5m

# 5. Проверка DNS A-записи через dig
kubectl exec dns-test -- dig +short my-pod-0.my-headless-svc.default.svc.cluster.local
# → 10.244.1.5   ← если пусто — проблема в CoreDNS
```

**Решение:**
```bash
# 1. Убедитесь, что Service headless (clusterIP: None)
kubectl get svc my-headless-svc -o yaml | grep clusterIP
# → clusterIP: None

# 2. Перезапустить CoreDNS для обновления кэша
kubectl rollout restart deployment coredns -n kube-system

# 3. Проверить, что StatefulSet имеет правильный serviceName
kubectl get statefulset my-app -o yaml | grep serviceName
# → serviceName: my-headless-svc

# 4. Подождать обновления DNS (обычно 30 сек)
kubectl exec dns-test -- nslookup my-pod-0.my-headless-svc.default.svc.cluster.local
# → Name:      my-pod-0.my-headless-svc.default.svc.cluster.local
# → Address:   10.244.1.5
```

---

### Сценарий 6: Reverse DNS (PTR) не работает

**Симптом**: kubelet не может пройти TLS-аутентификацию из-за отсутствия PTR-записи. Логи: `x509: cannot validate certificate for <ip> because it doesn't contain any IP SANs`.

**Диагностика:**
```bash
# 1. Проверка PTR-записи
dig -x 10.0.1.10 +short
# → (пусто)   ← PTR-записи нет

# 2. Проверка, какой hostname возвращает PTR
nslookup 10.0.1.10
# → 10.0.1.10.in-addr.arpa name = node-1.lab.local

# 3. Проверка SAN в сертификате
openssl x509 -in /var/lib/kubelet/pki/kubelet-server-current.pem -text -noout | grep -A 3 "Subject Alternative Name"
# → IP Address:10.0.1.10   ← SAN содержит IP, PTR не критичен
```

**Решение:**
```bash
# 1. Добавить PTR-запись в DNS (на стороне DNS-сервера)
# ДляBIND/named:
# 10.0.1.10.in-addr.arpa.  IN PTR node-1.lab.local.

# 2. Или добавить IP SAN в сертификат (если PTR недоступен)
# kubelet автоматически добавляет IP SAN, если hostname-override не используется

# 3. Проверка SAN
openssl x509 -in /var/lib/kubelet/pki/kubelet-server-current.pem -text -noout | grep -A 5 "Subject Alternative Name"
# → DNS:node-1, IP Address:10.0.1.10
```

## Мониторинг и алертинг

### Метрики hostname/DNS

| Метрика (node_exporter) | Описание | Типичный порог алерта |
| :--- | :--- | :--- |
| `node_boot_time_seconds` | Время загрузки узла | Изменение > 0 (reboot) |
| `node_timex_offset_seconds` | Расхождение с NTP | > 1持续 5 минут |
| `node_dns_resolution_success` | Успешность DNS-резолва | == 0持续 |

### Примеры алертов

```yaml
groups:
  - name: hostname-dns
    rules:
      - alert: NodeHostnameMismatch
        expr: node_uname_info{field_nodename!="nodename"} == 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Hostname узла {{ $labels.instance }} не совпадает"
          description: "System hostname и Kubernetes node name различаются."

      - alert: NodeDNSResolutionFailed
        expr: probe_dns_lookup_time_seconds > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "DNS-резолв медленный на {{ $labels.instance }}"
          description: "DNS-резолв занимает > 5 секунд."

      - alert: NodeRebootDetected
        expr: changes(node_boot_time_seconds[5m]) > 0
        for: 1m
        labels:
          severity: info
        annotations:
          summary: "Обнаружена перезагрузка {{ $labels.instance }}"
          description: "Узел был перезагружен. Проверьте статус."
```

## Дополнительная информация

### Полезные команды

```bash
# Hostname
hostname                          # Текущий hostname
hostname -f                       # FQDN
hostname -I                       # IP-адреса
hostnamectl status                # Статус hostname
sudo hostnamectl set-hostname X   # Установить hostname

# DNS
cat /etc/resolv.conf              # DNS-конфигурация
nslookup <name>                   # Резолв
dig <name>                        # Детальный резолв
dig +short <name>                 # Краткий резолв
dig -x <ip>                       # Reverse DNS (PTR)
host <ip>                         # Reverse DNS
getent hosts <name>               # Резолв через NSS

# /etc/hosts
grep $(hostname) /etc/hosts       # Проверка записи
cat /etc/hosts                    # Все записи
```

### Связанные разделы

- **[Проблемы Kubelet](./kubelet_issues.md)** — hostname и TLS-сертификаты
- **[Сетевые проблемы](./network_issues.md)** — DNS-резолв, CoreDNS
- **[Diagnostика узла](./diagnostics.md)** — hostname как часть диагностики
- **[StatefulSet: DNS](../../../Kubernetes/Base/StatefulSet/statefulset_core_concepts.md)** — DNS для StatefulSet
- **[Node Preparation](../../../Kubernetes/Installation/HA_Cluster_Bare_Metal/k8s_ha_node_preparation.md)** — настройка hostname перед установкой
- **[NTP и время](./time_sync.md)** — время влияет на TLS и hostname
