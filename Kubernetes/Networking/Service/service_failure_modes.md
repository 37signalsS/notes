# Отказоустойчивость Service: Failure Modes и Каскадные Сбои

## Определения

**Failure Mode (Режим отказа)** — предсказуемое поведение системы при нарушении работы одного или нескольких компонентов. Понимание failure modes Service критично для проектирования отказоустойчивых приложений и реагирования на инциденты.

**Cascading Failure (Каскадный сбой)** — цепная реакция, при которой сбой одного компонента вызывает сбои в зависимых системах, potentially приводя к полной неработоспособности сервиса или кластера.

**Graceful Degradation (Плавная деградация)** — способность системы продолжать работу с ограниченной функциональностью при частичном отказе компонентов.

---

## Основные концепции

### Архитектура отказоустойчивости Service

Service опирается на несколько компонентов, каждый из которых является потенциальной точкой отказа:

```
CoreDNS (Service Discovery)
    |
API-сервер (хранение состояния Service/EndpointSlice)
    |
EndpointSlice Controller (управление эндпоинтами)
    |
kube-proxy (программирование правил на узлах)
    |
CNI-плагин (сетевая связность подов)
    |
Приложение (readiness/liveness probes)
```

### Классификация отказов

| Тип отказа | Влияние на Service | Время восстановления | Критичность |
| :--- | :--- | :--- | :--- |
| **Падение одного пода** | Трафик перераспределяется между оставшимися репликами | Мгновенно (автоматическое) | Низкая |
| **Падение всех подов в AZ** | Service работает через оставшиеся AZ | Мгновенно (при наличии реплик) | Средняя |
| **Падение CoreDNS** | Service Discovery недоступен, DNS не резолвится | Требует вмешательства | Высокая |
| **Падение kube-proxy** | Service на узле недоступен | Требует перезапуска DaemonSet | Высокая |
| **Падение API-сервера** | EndpointSlice не обновляются | Критично | Критическая |
| **Переполнение conntrack** | Новые соединения отбрасываются | Требует настройки sysctl | Высокая |
| **Исчерпание ClusterIP** | Новые Service не могут быть созданы | Требует добавления ServiceCIDR | Средняя |

---

## Практические сценарии

### Failure Mode 1: Падение CoreDNS

**Симптом:** Приложения не могут обратиться к Service по DNS-имени. Обращение по ClusterIP работает.

**Диагностика:**
```bash
# 1. Проверка статуса CoreDNS
kubectl -n kube-system get pods -l k8s-app=kube-dns
# -> Если поды не в Running - CoreDNS недоступен

# 2. Проверка DNS из тестового пода
kubectl run dns-test --rm -it --image=busybox:1.37 -- nslookup kubernetes.default
# -> SERVFAIL или timeout - DNS не работает

# 3. Проверка EndpointSlices CoreDNS
kubectl -n kube-system get endpointslice -l kubernetes.io/service-name=kube-dns
# -> Должен содержать IP подов CoreDNS
```

**Восстановление:**
```bash
# Перезапуск CoreDNS
kubectl -n kube-system rollout restart deployment/coredns

# Проверка логов
kubectl -n kube-system logs -l k8s-app=kube-dns --tail=50
```

**Влияние на Service:**
- ClusterIP Service продолжают работать (правила kube-proxy уже запрограммированы)
- Новые обращения по DNS-именам невозможны
- Headless Service полностью неработоспособны (DNS - единственный механизм discovery)

### Failure Mode 2: Падение kube-proxy на узле

**Симптом:** Приложения на определенном узле не могут обращаться к Service по ClusterIP.

**Диагностика:**
```bash
# 1. Проверка kube-proxy на проблемном узле
kubectl -n kube-system get pods -l k8s-app=kube-proxy -o wide | grep <node-name>

# 2. Проверка правил на узле
sudo iptables -t nat -L KUBE-SERVICES -n | head -20

# 3. Проверка логов kube-proxy
kubectl -n kube-system logs -l k8s-app=kube-proxy --field-selector spec.nodeName=<node-name> --tail=50
```

**Восстановление:**
```bash
# Перезапуск DaemonSet kube-proxy
kubectl -n kube-system rollout restart daemonset/kube-proxy
```

### Failure Mode 3: Переполнение conntrack

**Симптом:** Периодические таймауты под нагрузкой. В логах ядра: `nf_conntrack: table full, dropping packet`.

**Диагностика:**
```bash
# Проверка использования conntrack
sudo conntrack -C
sysctl net.netfilter.nf_conntrack_max
sudo conntrack -S
```

**Восстановление:**
```bash
# Увеличение лимита conntrack
sudo sysctl -w net.netfilter.nf_conntrack_max=1310720
echo "net.netfilter.nf_conntrack_max = 1310720" | sudo tee -a /etc/sysctl.conf
```

**Постоянное решение:** Переключение на IPVS или eBPF режим kube-proxy, снижение таймаутов conntrack.

### Failure Mode 4: Исчерпание ClusterIP диапазона

**Симптом:** `Failed to allocate IP for <service-name>: no available IPs`.

**Диагностика:**
```bash
kubectl get servicecidr
kubectl get svc -A | wc -l
```

**Восстановление (Kubernetes 1.31+):**
```bash
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1alpha1
kind: ServiceCIDR
metadata:
  name: additional-cidr
spec:
  cidrs:
    - 10.97.0.0/16
EOF
```

---

## Каскадные сбои: Сценарии и защита

### Сценарий 1: CoreDNS -> Service Discovery -> Приложения

```
CoreDNS падает
    |
DNS не резолвится
    |
Приложения не могут найти другие сервисы
    |
Микросервисы теряют связность
    |
Полная неработоспособность платформы
```

**Защита:**
- Реплики CoreDNS (min 2-3 в разных AZ)
- NodeLocal DNSCache (локальный DNS-кеш на каждом узле)
- Retry-логика в приложениях с exponential backoff
- Fallback на IP-адреса для критичных сервисов

### Сценарий 2: API-сервер -> EndpointSlice -> kube-proxy

```
API-сервер недоступен
    |
EndpointSlice Controller не обновляет эндпоинты
    |
Поды удаляются/создаются, но эндпоинты не меняются
    |
Service направляет трафик на мертвые поды (5xx ошибки)
    |
Клиенты получают ошибки, retry加剧 нагрузку
```

**Защита:**
- Группировка кластеров control plane (3+ ноды)
- EndpointSlice cache в kube-proxy (продолжает работать при кратковременной недоступности API)
- Circuit breaker в приложениях
- Health check на стороне балансировщика

### Сценарий 3: kube-proxy -> conntrack -> все Service

```
Высокая нагрузка на kube-proxy
    |
Медленное обновление правил
    |
Переполнение conntrack
    |
Новые соединения отбрасываются
    |
Все Service на узле недоступны
    |
Каскадный отказ приложений
```

**Защита:**
- Мониторинг conntrack utilization (алерт при >80%)
- Переключение на IPVS/eBPF (снижение нагрузки на conntrack)
- Ограничение rate на уровне Service (ResourceQuota)

---

## Best Practices для отказоустойчивости

1. **Минимум 2 реплики CoreDNS** в разных Availability Zones
2. **NodeLocal DNSCache** для снижения нагрузки на CoreDNS и повышения отказоустойчивости DNS
3. **PodDisruptionBudget** для критичных Service (minAvailable >= 2)
4. **readinessProbe** с足够 строгими проверками для исключения неработоспособных подов из эндпоинтов
5. **PreStop хук** для плавного завершения соединений перед удалением пода
6. **Мониторинг ключевых метрик:**
   - `kube_proxy_sync_proxy_rules_duration_seconds` (синхронизация правил)
   - `kube_proxy_service_changes_total` (частота изменений)
   - `conntrack -C` / `nf_conntrack_max` (использование conntrack)
   - Endpoints ready count для каждого Service
7. **Circuit breaker** в приложениях для предотвращения каскадных сбоев
8. **Rate limiting** на уровне Service для защиты от thundering herd

## Дополнительная информация

### Связанные темы

- **Conntrack tuning:** [NetworkPolicy Performance](../Network/NetworkPolicy/performance.md) - настройка conntrack для Production
- **kube-proxy:** [kube-proxy](../Network/kube-proxy.md) - детали режимов работы и мониторинга
- **Network Troubleshooting:** [Network Troubleshooting](../Network/kubernetes_network_troubleshooting.md) - систематический подход к диагностике
- **Chaos Engineering:** [Chaos Monkey](../../../Chaos_Engineering/chaos_monkey_concept.md) - тестирование отказоустойчивости

### См. также

- [Обзор Service](./service_overview.md) - архитектура и механизмы работы
- [Продвинутая диагностика](./service_advanced_troubleshooting.md) - tcpdump, netshoot, conntrack deep dive
- [NetworkPolicy + Service](./service_network_policy_integration.md) - паттерны сетевой изоляции
