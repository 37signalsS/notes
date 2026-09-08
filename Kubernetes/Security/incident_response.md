# Реагирование на инциденты безопасности в Kubernetes

## Определения

**Инцидент безопасности (Security Incident)** — событие, угрожающее конфиденциальности, целостности или доступности (CIA) кластера, подов, узлов или данных. В контексте Kubernetes типичными инцидентами являются: компрометация пода, криптомайнинг, lateral movement, утечка секретов, компрометация узла, несанкционированный доступ к API-серверу.

**DFIR (Digital Forensics and Incident Response)** — совокупность методов обнаружения, реагирования, смягчения последствий и расследования инцидентов безопасности. Включает сбор доказательств, анализ временной шкалы (timeline) и восстановление нормальной работы.

**Карантин (Quarantine)** — изоляция скомпрометированного ресурса (под, узел) от остальной инфраструктуры с сохранением его работоспособности для последующего анализа. В Kubernetes реализуется через NetworkPolicy, отключение от Service, изменение меток.

**Lateral Movement (Боковое перемещение)** — движение атакующего от скомпрометированного компонента к другим ресурсам кластера. В Kubernetes это доступ к другим подам, секретам, API-серверу или узлам через незащищенную сеть между подами.

**Blast Radius (Радиус поражения)** — масштаб потенциального ущерба при компрометации одного компонента. Ограничивается микросегментацией (NetworkPolicy), RBAC, Pod Security Admission и изоляцией неймспейсов.

**Chain of Custody (Цепь хранения)** — документированный процесс сбора, хранения и передачи цифровых доказательств с целью обеспечения их целостности и допустимости в качестве улик.

---

## Основные концепции

### Модель реагирования на инциденты (Incident Response Lifecycle)

Процесс реагирования следует стандарту NIST SP 800-61 и адаптирован для Kubernetes:

```
1. Подготовка (Preparation)
   ├── Runbook'и и плейбуки
   ├── Инструменты мониторинга (Falco, Prometheus, Audit Logs)
   ├── RBAC и ограничение доступа
   └── Регулярные drills ( tabletop exercises)

2. Обнаружение и классификация (Detection & Classification)
   ├── Алерты из Falco / Prometheus / Audit Log
   ├── Определение SEV уровня (SEV-1 .. SEV-4)
   └── Идентификация затронутых ресурсов

3. Содержание и локализация (Containment)
   ├── Изоляция пода (NetworkPolicy quarantine)
   ├── Изоляция узла (drain + taint)
   ├── Блокировка ServiceAccount
   └── Предотвращение lateral movement

4. Ликвидация (Eradication)
   ├── Удаление скомпрометированных подов
   ├── Ротация секретов и сертификатов
   ├── Обновление политик безопасности
   └── Патчинг уязвимостей

5. Восстановление (Recovery)
   ├── Перезапуск подов из чистых образов
   ├── Проверка целостности данных
   ├── Валидация политик безопасности
   └── Мониторинг на предмет повторного вторжения

6. Анализ после инцидента (Postmortem)
   ├── Blameless Postmortem
   ├── Root Cause Analysis (5 Whys)
   ├── Определение времени компрометации (MTTD)
   └── Меры по предотвращению повторения
```

### Типология инцидентов в Kubernetes

| Тип инцидента | SEV | Типичные признаки | Источник обнаружения |
|:---|:---|:---|:---|
| Компрометация пода | SEV-1/2 | Аномальные syscall, несанкционированный доступ к файлам, сетевые соединения наружу | Falco, Audit Log |
| Криптомайнинг | SEV-2 | Высокая загрузка CPU, известные pool'и майнинга, аномальные сетевые соединения | Prometheus, Falco |
| Утечка секретов | SEV-1 | Доступ к `/var/run/secrets/`, exfiltration данных, чтение Secret через API | Falco, Audit Log |
| Компрометация узла | SEV-1 | Нестандартные процессы в hostPID/hostNetwork, модификация kubelet | Audit Log, node exporter |
| Lateral movement | SEV-1/2 | Сканирование сети, попытки доступа к другим подам/сервисам | NetworkPolicy logs, Falco |
| Несанкционированный доступ к API | SEV-1 | 403/401 ошибки, impersonation, создание привилегированных подов | Audit Log, API server metrics |
| Supply chain атака | SEV-1 | Внедрение бэкдора в образ, модификация CI/CD pipeline | Image scanning, SBOM verification |
| DoS на API-сервер | SEV-2 | Резкий рост запросов, таймауты, отказ в обслуживании | API server metrics, Prometheus |

### Уровни инцидентов (Severity Levels)

| Уровень | Описание | Время реакции | Пример |
|:---|:---|:---|:---|
| **SEV-1** | Критический: компрометация control plane, mass lateral movement, утечка всех секретов | 15 минут | Компрометация etcd, API-сервера |
| **SEV-2** | Высокий: компрометация отдельного пода/узла, криптомайнинг | 30 минут | Под с cryptominer, утечка Secret |
| **SEV-3** | Средний: несанкционированный доступ, нарушение политик | 2 часа | PSA violation, RBAC misconfiguration |
| **SEV-4** | Низкий: подозрительная активность, шум | 24 часа | Аномальные логи, failed auth attempts |

### Архитектура обнаружения (Detection Stack)

```
┌─────────────────────────────────────────────────────┐
│                  Источники событий                   │
├─────────────┬───────────────┬───────────────────────┤
│   Falco     │  Audit Log    │  Prometheus/Alertmgr  │
│ (syscall)   │  (API calls)  │  (метрики, алерты)    │
└──────┬──────┴───────┬───────┴───────────┬───────────┘
       │              │                   │
       ▼              ▼                   ▼
┌─────────────────────────────────────────────────────┐
│              Агрегация и маршрутизация               │
├─────────────┬───────────────┬───────────────────────┤
│Policy Reporter│  Loki/SIEM   │  Alertmanager         │
│ (OpenReports) │ (логи)       │  (алерты)             │
└──────┬──────┴───────┬───────┴───────────┬───────────┘
       │              │                   │
       ▼              ▼                   ▼
┌─────────────────────────────────────────────────────┐
│              Реагирование и действие                 │
├─────────────┬───────────────┬───────────────────────┤
│ Falcosidekick│  PagerDuty/   │  Автоматический       │
│ (webhook)    │  Slack        │  quarantine           │
└─────────────┴───────────────┴───────────────────────┘
```

### Связь с другими системами безопасности

Реагирование на инциденты опирается на несколько слоев защиты (Defense in Depth):

| Слой | Компонент | Роль в инциденте | Документ |
|:---|:---|:---|:---|
| Admission | Pod Security Admission, Kyverno | Предотвращение запуска небезопасных подов | [Pod Security Context](./pod_security_context.md) |
| Сеть | NetworkPolicy | Изоляция (quarantine) скомпрометированных подов | [Network Policies](./network_policies.md) |
| Авторизация | RBAC | Ограничение прав субъектов, предотвращение escalation | [RBAC](./rbac/rbac_overview.md) |
| Мониторинг | Falco, Audit Log | Обнаружение аномалий в реальном времени | [Audit](./audit.md) |
| Идентификация | Authentication, OIDC | Определение личности атакующего | [Authentication](./authentication.md) |

---

## Практические сценарии

### Сценарий 1: Обнаружение криптомайнера в поде

**Признаки:** Высокая загрузка CPU, аномальные сетевые соединения наружу, известные pool'и майнинга в логах.

**Действия:**

```bash
# 1. Идентификация пода с аномальной загрузкой CPU
kubectl top pods --sort-by=cpu -A | head -20
# → suspicious-pod-abc123   950m   128Mi

# 2. Проверка логов Falco на наличие криптомайнинга
kubectl logs -n falco-system -l app.kubernetes.io/name=falco --tail=50 | grep -i "mine\|crypto\|stratum"
# → Alert: Container started mining crypto (rule=crypto_mining)
# → Priority: CRITICAL

# 3. Проверка сетевых соединений пода через PID
kubectl exec -n production suspicious-pod-abc123 -- ss -tlnp
# → ESTAB  0  0  10.244.1.5:44532  185.199.108.153:3333  users:(("xmrig",pid=1,fd=7))

# 4. Карантин пода через NetworkPolicy
cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: quarantine-suspicious-pod
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: suspicious-app
  policyTypes:
  - Ingress
  - Egress
  ingress: []
  egress: []
EOF
# → Полная изоляция пода от сетевого трафика

# 5. Изменение метки пода для标识
kubectl label pod suspicious-pod-abc123 -n production quarantine=true security-incident=SEV2-cryptominer

# 6. Сбор forensics данных
kubectl describe pod suspicious-pod-abc123 -n production > /tmp/forensics/pod-describe-$(date +%Y%m%d).txt
kubectl logs suspicious-pod-abc123 -n production --previous > /tmp/forensics/pod-logs-$(date +%Y%m%d).txt
kubectl get pod suspicious-pod-abc123 -n production -o yaml > /tmp/forensics/pod-manifest-$(date +%Y%m%d).yaml

# 7. Добавление ephemeral контейнера для forensic анализа (если под работает)
kubectl debug -it suspicious-pod-abc123 -n production --image=busybox --target=app -- sh
# → Сбор артефактов: /proc/1/cmdline, /proc/1/environ, сетевые соединения

# 8. Удаление скомпрометированного пода после сбора данных
kubectl delete pod suspicious-pod-abc123 -n production

# 9. Ротация секретов, которые мог быть скомпрометированы
kubectl get secrets -n production -o name | xargs -I {} kubectl rollout restart deployment -n production

# 10. Проверка, что под пересоздан без майнера
kubectl top pods -n production --sort-by=cpu | head -5
```

**Проверка:** После удаления пода Deployment/ReplicaSet пересоздаст его. Если образ компрометирован, майнер появится снова. Необходимо обновить образ или заблокировать его через ImagePolicy.

### Сценарий 2: Карантин скомпрометированного пода через NetworkPolicy

**Паттерн:** Полная изоляция пода от сетевого трафика с сохранением его работоспособности для анализа.

```bash
# 1. Применение карантинной политики (полная блокировка)
cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: quarantine-full-isolation
  namespace: production
  labels:
    purpose: security-incident
    incident-id: "INC-2026-001"
spec:
  podSelector:
    matchLabels:
      security-incident: "INC-2026-001"
  policyTypes:
  - Ingress
  - Egress
  ingress: []
  egress: []
EOF

# 2. Проверка применения политики
kubectl get networkpolicy -n production -l purpose=security-incident
# → NAME                    POD-SELECTOR                    AGE
# → quarantine-full-isolation  security-incident=INC-2026-001  30s

# 3. Верификация изоляции (с другого пода)
kubectl exec -n production legitimate-pod -- curl -s --connect-timeout=3 http://suspicious-service.production.svc.cluster.local
# → curl: (28) Connection timed out after 3 seconds

# 4. Сбор данных о lateral movement (проверка логов)
kubectl logs -n production suspicious-pod-abc123 --previous | grep -E "connect\|exec\|secret|serviceaccount"
# → 2026-09-07T10:15:33Z [notice] Opened connection to 10.244.2.15:5432 (database)
# → 2026-09-07T10:15:45Z [notice] Read file /var/run/secrets/kubernetes.io/serviceaccount/token

# 5. После анализа — удаление карантинной политики и пода
kubectl delete networkpolicy quarantine-full-isolation -n production
kubectl delete pod suspicious-pod-abc123 -n production
```

### Сценарий 3: Реагирование на компрометацию ServiceAccount

**Признаки:** Необычные запросы к API-серверу от имени ServiceAccount, попытки создания привилегированных подов, доступ к секретам в других неймспейсах.

```bash
# 1. Определение ServiceAccount, используемого подом
kubectl get pod suspicious-pod-abc123 -n production -o jsonpath='{.spec.serviceAccountName}'
# → default

# 2. Проверка绑定 к SA
kubectl get rolebinding,clusterrolebinding -A -o wide | grep "serviceaccount:production:default"
# → default-role-binding   ClusterRole/cluster-view   serviceaccount:production:default

# 3. Блокировка токена SA через обновление automount
kubectl patch serviceaccount default -n production -p '{"automountServiceAccountToken": false}'

# 4. Перезапуск подов для применения новых настроек
kubectl rollout restart deployment -n production

# 5. Проверка RBAC привязаний SA
kubectl auth can-i --list --as=system:serviceaccount:production:default -n production
# → Проверка: какие права имеет SA

# 6. Ротация токена SA (создание нового)
kubectl delete secret $(kubectl get secret -n production -o jsonpath='{.items[?(@.metadata.annotations.kubernetes\.io/service-account\.name=="default")].metadata.name}') -n production
# → Токен будет пересоздан при следующем монтировании

# 7. Проверка Audit Log на активность SA
kubectl logs -n kube-system -l component=kube-apiserver --tail=1000 | grep "serviceaccount:production:default" | grep -E "create|get.*secret|list"
# → Анализ всех запросов, выполненных от имени скомпрометированного SA
```

### Сценарий 4: Сбор forensics данных с помощью ephemeral containers

**Цель:** Получение артефактов из работающего пода без его остановки.

```bash
# 1. Добавление debug контейнера к поду
kubectl debug -it suspicious-pod-abc123 -n production \
  --image=busybox:1.36 \
  --target=app \
  -- /bin/sh

# 2. Внутри debug контейнера — сбор артефактов
# Копирование процессов
ps auxf > /tmp/forensics/processes.txt

# Копирование сетевых соединений
ss -tlnp > /tmp/forensics/network_listening.txt
ss -tanp > /tmp/forensics/network_established.txt

# Копирование командной строки процесса
cat /proc/1/cmdline | tr '\0' ' ' > /tmp/forensics/cmdline.txt

# Копирование переменных окружения
cat /proc/1/environ | tr '\0' '\n' > /tmp/forensics/environ.txt

# Проверка установленных пакетов (если есть apk/apt)
apk list --installed > /tmp/forensics/installed_packages.txt 2>/dev/null || true
dpkg -l > /tmp/forensics/installed_packages.txt 2>/dev/null || true

# Проверка crontab
crontab -l > /tmp/forensics/crontab.txt 2>/dev/null || true

# Проверка файловой системы на подозрительные файлы
find /tmp /var/tmp /dev/shm -type f -mtime -1 2>/dev/null > /tmp/forensics/recent_files.txt
find / -perm -4000 2>/dev/null > /tmp/forensics/suid_files.txt

# 3. Копирование данных из контейнера наружу
kubectl cp production/suspicious-pod-abc123:/tmp/forensics /tmp/forensics-collected/ -c debug-container

# 4. Проверка артефактов
ls -la /tmp/forensics-collected/
# → processes.txt  network_listening.txt  cmdline.txt  environ.txt  ...
```

### Сценарий 5: Реагирование на компрометацию узла

**Признаки:** Нестандартные процессы на хосте, модификация kubelet, попытки container escape.

```bash
# 1. Изоляция узла (drain + taint)
kubectl drain node01 --ignore-daemonsets --delete-emptydir-data --force

# 2. Добавление taint для предотвращения планирования новых подов
kubectl taint nodes node01 security-incident=true:NoExecute

# 3. Проверка процессов на узле (через SSH)
ssh node01
ps auxf | grep -v -E "kubelet|containerd|etcd|kube-proxy"
# → Подозрительные процессы

# 4. Проверка модулей ядра
lsmod | grep -v -E "kvm|vfio|br_netfilter|overlay"
# → Неизвестные модули

# 5. Проверка crontab на узле
crontab -l
for user in $(cut -f1 -d: /etc/passwd); do crontab -u $user -l 2>/dev/null; done

# 6. Проверка файловой системы на изменения
find /usr/bin /usr/sbin /usr/local/bin -mtime -7 -type f 2>/dev/null
# → Недавно измененные бинарные файлы

# 7. Проверка сетевых соединений
ss -tlnp | grep -v -E "kubelet|containerd|etcd"
# → Подозрительные слушающие порты

# 8. Сбор логов kubelet
journalctl -u kubelet --since "1 hour ago" > /tmp/forensics/kubelet-logs.txt

# 9. После анализа — восстановление узла
# Переустановка K8s компонентов, ротация сертификатов
kubeadm init phase kubelet start # или appropriate command

# 10. Снятие taint и возврат узла в кластер
kubectl taint nodes node01 security-incident=true:NoExecute-
kubectl uncordon node01
```

### Сценарий 6: Обнаружение несанкционированного доступа через Audit Log

```bash
# 1. Поиск подозрительных запросов к секретам
kubectl logs -n kube-system -l component=kube-apiserver --tail=10000 | \
  jq -r 'select(.verb == "get" or .verb == "list") | select(.objectRef.resource == "secrets") | "\(.user.username) \(.requestReceivedTimestamp) \(.objectRef.namespace)/\(.objectRef.name)"' | \
  grep -v "system:serviceaccount:kube-system"
# → анонимный пользователь пытался получить секреты

# 2. Поиск попыток создания привилегированных подов
kubectl logs -n kube-system -l component=kube-apiserver --tail=10000 | \
  jq -r 'select(.verb == "create") | select(.objectRef.resource == "pods") | select(.requestObject.spec.containers[].securityContext.privileged == true) | "\(.user.username) \(.requestReceivedTimestamp) \(.objectRef.namespace)"'

# 3. Поиск impersonation
kubectl logs -n kube-system -l component=kube-apiserver --tail=10000 | \
  jq -r 'select(.user.username | startswith("system:anonymous")) | "\(.requestReceivedTimestamp) \(.verb) \(.objectRef.resource) \(.responseStatus.code)"' | \
  grep -v "401"

# 4. Поиск успешных аутентификаций после серии 401
kubectl logs -n kube-system -l component=kube-apiserver --tail=10000 | \
  jq -r 'select(.responseStatus.code == 200 or .responseStatus.code == 201) | "\(.user.username) \(.requestReceivedTimestamp) \(.verb) \(.objectRef.resource)"' | \
  head -20

# 5. Экспорт подозрительных событий для анализа
kubectl logs -n kube-system -l component=kube-apiserver --tail=10000 | \
  jq 'select(.user.username | test("anonymous|system:anonymous"))' > /tmp/forensics/suspicious-api-calls.json
```

---

## Диагностические команды

### Обнаружение инцидентов

| Команда | Назначение |
|:---|:---|
| `kubectl top pods --sort-by=cpu -A` | Обнаружение подов с аномальным потреблением CPU (криптомайнинг) |
| `kubectl top pods --sort-by=memory -A` | Обнаружение подов с аномальным потреблением памяти |
| `kubectl get pods -A -o wide \| grep -v kube-system` | Список всех прикладных подов с привязкой к узлам |
| `kubectl get networkpolicy -A` | Проверка примененных сетевых политик |
| `kubectl auth can-i --list --as=system:serviceaccount:ns:sa` | Проверка прав SA |
| `kubectl get pods -A -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.serviceAccountName}{"\n"}{end}'` | Маппинг подов на SA |

### Сбор данных

| Команда | Назначение |
|:---|:---|
| `kubectl describe pod <name> -n <ns>` | Детальное описание пода |
| `kubectl logs <name> -n <ns> --previous` | Логи предыдущего контейнера |
| `kubectl get pod <name> -n <ns> -o yaml` | Манифест пода |
| `kubectl exec -it <name> -n <ns> -c <container> -- /bin/sh` | Интерактивный доступ |
| `kubectl debug -it <name> -n <ns> --image=busybox --target=<container>` | Ephemeral debug контейнер |
| `kubectl cp <ns>/<pod>:/path ./local-path -c <container>` | Копирование файлов из пода |

### Изоляция

| Команда | Назначение |
|:---|:---|
| `kubectl label pod <name> quarantine=true` | Метка для карантинной политики |
| `kubectl patch sa <name> -n <ns> -p '{"automountServiceAccountToken": false}'` | Блокировка токена SA |
| `kubectl drain <node> --ignore-daemonsets --delete-emptydir-data` | Изоляция узла |
| `kubectl taint nodes <node> security-incident=true:NoExecute` | Запрет планирования на узел |

---

## Best Practices

1. **Подготовка до инцидента:** Имейте готовые runbook'и, карантинные NetworkPolicy шаблоны и инструменты forensics (busybox, sysdig) в каждом неймспейсе.
2. **Минимальные привилегии:** `automountServiceAccountToken: false` для всех подов, которые не обращаются к K8s API. Ограничивайте RBAC через principle of least privilege.
3. **Defense in Depth:** Сочетайте Pod Security Admission (restricted), NetworkPolicy (default deny), RBAC и Audit Logging.
4. **Регулярные drills:** Проводите tabletop exercises минимум раз в квартал. Тестируйте сценарии: компрометация пода, утечка секретов, криптомайнинг.
5. **Сбор доказательств:** Всегда собирайте forensics данные ДО удаления пода. Используйте `kubectl debug` для ephemeral containers, `kubectl cp` для копирования артефактов.
6. **Временная шкала:** Поддерживайте синхронизацию времени (NTP/PTP) на всех узлах для корректной корреляции событий в Audit Log и Falco.
7. **Автоматизация:** Настройте Falcosidekick для автоматического quarantine через webhook (AWS Lambda,_SCRIPT, custom endpoint).
8. **Ротация после инцидента:** После любого инцидента ротируйте все секреты, сертификаты и ServiceAccount токены в затронутом неймспейсе.

---

## Дополнительная информация

### Связанные документы

- [Network Policies — quarantine pattern](./network_policies.md)
- [Ephemeral Containers — forensic workflow](../Base/Pod/ephemeral_containers.md)
- [Audit — аудит в Kubernetes](./audit.md)
- [Pod Security Context — безопасность подов](./pod_security_context.md)
- [RBAC — управление доступом](./rbac/rbac_overview.md)
- [Authentication — аутентификация](./authentication.md)
- [Falco — runtime security](../../Security/Tools/falco.md)

### Внешние ресурсы

- [NIST SP 800-61 — Computer Security Incident Handling Guide](https://csrc.nist.gov/publications/detail/sp/800-61/rev-2/final)
- [MITRE ATT&CK — Kubernetes](https://attack.mitre.org/matrices/enterprise/kubernetes/)
- [Kubernetes Incident Response — Trail of Bits](https://blog.trailofbits.com/2023/02/16/kubernetes-security/)
