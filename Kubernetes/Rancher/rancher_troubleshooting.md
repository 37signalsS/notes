# Troubleshooting в Rancher

## Определения

**Troubleshooting** — систематический процесс диагностики и устранения неполадок в Rancher и управляемых кластерах. Включает проверку компонентов, анализ логов, мониторинг метрик и пошаговое устранение проблем.

**cattle-cluster-agent** — компонент в downstream-кластере, обеспечивающий туннель к Rancher Server. Отвечает за связь между Management и Downstream кластерами.

**cattle-node-agent** — агент на узлах Node Driver кластера, управляющий жизненным циклом узла (установка RKE2, обновления).

**System Agent** — бинарный файл, устанавливаемый на узлы для связи с Rancher Server. Запускается как systemd-сервис.

## Базовые концепции

### Архитектура диагностики

```
Rancher Server → cattle-cluster-agent → Kubernetes API → Поды/Узлы
       ↑                    ↑                    ↑
   Логи Rancher       Логи агента         kubectl logs
   /v3 API            туннеля             events, describe
```

**Принцип диагностики:** начинайте с Rancher Server → проверьте агенты → проверьте кластер → проверьте конкретный ресурс.

### Уровни диагностики

| Уровень | Компонент | Инструменты |
| :--- | :--- | :--- |
| **1. Rancher Server** | Deployment `rancher` | `kubectl -n cattle-system logs`, UI |
| **2. Агенты** | `cattle-cluster-agent`, `cattle-node-agent` | `kubectl -n cattle-system get pods`, логи |
| **3. Kubernetes** | API Server, etcd, kubelet | `kubectl get nodes`, `kubectl get pods -A` |
| **4. Приложение** | Deployments, Services, Pods | `kubectl describe`, `kubectl logs` |

## Практические сценарии

### Сценарий 1: Rancher UI недоступен

**Симптом:** браузер не открывает `https://rancher.example.com`

```bash
# 1. Проверка подов Rancher Server
kubectl -n cattle-system get pods
# → rancher-<hash>-<hash>    3/3     Running    (норма)
# → rancher-<hash>-<hash>    0/3     Pending    (проблема)

# 2. Проверка Ingress
kubectl -n cattle-system get ingress
# → rancher   <none>   rancher.example.com   ...   rancher (TLS)

# 3. Проверка Load Balancer
curl -vk https://rancher.example.com/v3 -o /dev/null -w '%{http_code}\n'
# → 200 (норма), 502/503 (проблема с балансировщиком)

# 4. Логи Rancher
kubectl -n cattle-system logs -l app=rancher --tail=100
```

**Типичные причины:**
- Load Balancer не направляет трафик на порт 443/80.
- TLS-сертификат невалиден (проверьте cert-manager).
- etcd Management-кластера недоступен.

### Сценарий 2: Downstream-кластер в состоянии Unavailable

**Симптом:** в Rancher UI кластер помечен красным, статус "Unavailable"

```bash
# 1. Проверка cattle-cluster-agent в downstream
kubectl -n cattle-system get pods -l app=cattle-cluster-agent
# → cattle-cluster-agent-<hash>   CrashLoopBackOff   (проблема)

# 2. Логи агента
kubectl -n cattle-system logs -l app=cattle-cluster-agent -c cluster-register --tail=100
# → ищите ошибки: "dial tcp ... connection refused", "certificate", "unauthorized"

# 3. Проверка исходящей связности (на узле downstream)
curl -v https://<rancher-fqdn>/v3 -o /dev/null
# → должен вернуть 200

# 4. Проверка туннеля
kubectl -n cattle-system get pods -l app=cattle-cluster-agent -o yaml | grep -A5 "env:"
```

**Типичные причины:**
- Неверный CA-сертификат Rancher Server.
- Исходящий доступ к Rancher по 443 заблокирован.
- Токен кластера истек или неверен.

### Сценарий 3: Pod в CrashLoopBackOff

**Симптом:** под перезапускается бесконечно

```bash
# 1. Проверка статуса пода
kubectl describe pod <pod-name> -n <namespace>
# → Conditions: Ready: False
# → Last State: Terminated: Reason: Error, Exit Code: 1

# 2. Логи контейнера
kubectl logs <pod-name> -n <namespace> --previous
# → ищите ошибки в stderr

# 3. Проверка ресурсов
kubectl top pod <pod-name> -n <namespace>
# → Memory: 256Mi / 256Mi (OOM Killed!)

# 4. Проверка событий
kubectl get events -n <namespace> --field-selector involvedObject.name=<pod-name>
```

**Типичные причины:**
- OOMKilled (нехватка памяти).
- Ошибка в конфигурации (невалидный YAML, отсутствие ConfigMap/Secret).
- CrashLoopBackOff из-за ошибки в приложении.

### Сценарий 4: kubectl возвращает Forbidden

**Симптом:** `Error from server (Forbidden): ... is forbidden`

```bash
# 1. Проверка прав текущего пользователя
kubectl auth can-i list pods -n <namespace>
# → no (проблема с RBAC)

# 2. Проверка RoleTemplateBinding
kubectl get clusterroletemplatebindings -A | grep <user>
kubectl get projectroletemplatebindings -A | grep <user>

# 3. Проверка RoleTemplate
kubectl get roletemplates <role-name> -o yaml

# 4. Проверка через Rancher UI
# Users & Authentication → Users → выберите пользователя → Permissions
```

**Типичные причины:**
- Пользователь не добавлен в проект/кластер.
- RoleTemplate не содержит нужных прав.
- Нет RoleBinding в целевом namespace.

### Сценарий 5: Обновление Kubernetes зависло

**Симптом:** Plan обновления в состоянии "Waiting" или "Blocked"

```bash
# 1. Проверка Plan
kubectl get plans.upgrade.cattle.io -A -o wide
# → STATUS: WaitingForPlan

# 2. Проверка System Upgrade Controller
kubectl -n cattle-system logs -l app=system-upgrade-controller --tail=50

# 3. Проверка PDB (блокирует drain)
kubectl get pdb -A -o wide
# → если minAvailable не позволяет выселить поды — проблема

# 4. Проверка узла
kubectl describe node <node-name> | grep -A5 "Conditions"
# → Ready: True (норма), False (проблема с kubelet)
```

**Решение:**
- Если PDB блокирует: временно ослабьте PDB или дождитесь завершения текущего rollout.
- Если kubelet не Ready: перезапустите kubelet на узле (`systemctl restart kubelet`).

### Сценарий 6: Secrets не читаются подом

**Симптом:** `MountVolume.SetUp failed for volume ... secret "xxx" not found`

```bash
# 1. Проверка существования Secret
kubectl get secret <secret-name> -n <namespace>

# 2. Проверка прав доступа
kubectl auth can-i get secret <secret-name> -n <namespace> --as=system:serviceaccount:<namespace>:<sa-name>
# → no (проблема с RBAC)

# 3. Проверка ServiceAccount
kubectl get sa <sa-name> -n <namespace> -o yaml
# → automountServiceAccountToken: true/false
```

### Сценарий 7: NetworkPolicy блокирует трафик

**Симптом:** поды не могут подключиться друг к другу

```bash
# 1. Проверка NetworkPolicy
kubectl get networkpolicy -n <namespace>
# → есть ли политики, разрешающие трафик?

# 2. Проверка через describe
kubectl describe networkpolicy <policy-name> -n <namespace>
# → в Rules: Ingress/Egress

# 3. Тестирование (временное удаление)
kubectl delete networkpolicy <policy-name> -n <namespace>
# → если заработало — проблема в NetworkPolicy
```

### Сценарий 8: etcd не здоров

**Симптом:** кластер нестабилен, ошибки API Server

```bash
# 1. Проверка etcd (на Master-узле)
sudo rke2 etcd-snapshot list

# 2. Проверка кворума
kubectl get etcd -n kube-system
# → EtcdCluster: Ready

# 3. Проверка fsync latency (метрики)
# через Prometheus: etcd_disk_wal_fsync_duration_seconds

# 4. Проверка дискового I/O (на узле)
sudo fio --name=test --rw=write --bs=4k --size=128m --fdatasync=1 --runtime=10
# → fsync latency должна быть < 10ms
```

## Диагностические команды (Шпаргалка)

### Общие команды

```bash
# Состояние кластера
kubectl cluster-info
kubectl get nodes
kubectl get pods -A | grep -v Running | grep -v Completed

# События (ошибки)
kubectl get events -A --field-selector type=Warning --sort-by=.lastTimestamp | tail -20

# Ресурсы
kubectl top nodes
kubectl top pods -A --sort-by=memory
```

### Rancher-specific

```bash
# Поды Rancher Server
kubectl -n cattle-system get pods

# cattle-cluster-agent
kubectl -n cattle-system get pods -l app=cattle-cluster-agent

# Логи Rancher
kubectl -n cattle-system logs -l app=rancher --tail=100

# GitRepo (Fleet)
kubectl get gitrepo -A

# Мониторинг
kubectl -n cattle-monitoring-system get pods
```

### Diagnostics bundle

Rancher позволяет собрать diagnostics bundle через UI:
1. Rancher UI → Support → Diagnostics → Generate Diagnostics Bundle
2. Содержит логи всех компонентов Rancher.

## Дополнительная информация

### Рекомендации по troubleshooting

1. **Начинайте с симптомов:** определите, на каком уровне проблема (Rancher, агент, кластер, приложение).
2. **Используйте logs:** логи — основной источник информации.
3. **Проверяйте события:** `kubectl get events` показывает историю проблем.
4. **Мониторьте метрики:** Prometheus/Grafana помогают выявить тренды.
5. **Документируйте:** фиксируйте решения проблем для будущего использования.

### Связанные темы

- [Установка Rancher Server](./rancher_installation.md) — диагностика установки.
- [Day-2 операции](./rancher_day2_operations.md) — обслуживание кластеров.
- [Мониторинг](./rancher_monitoring.md) — настройка алертинга.
- [Логирование](./rancher_logging.md) — сбор и анализ логов.

**Внешние ресурсы:**

- [Rancher Troubleshooting](https://ranchermanager.docs.rancher.com/troubleshooting)
- [Rancher GitHub Issues](https://github.com/rancher/rancher/issues)
