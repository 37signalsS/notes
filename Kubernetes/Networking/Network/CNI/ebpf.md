# eBPF в Kubernetes: Оптимизация сети, безопасности и наблюдаемости

## Определения

**eBPF (Extended Berkeley Packet Filter) в Kubernetes** — индустриальный стандарт (де-факто в 2026 году) для реализации высокопроизводительной сетевой связности, безопасности и наблюдаемости кластера на уровне ядра Linux без внесения изменений в код приложений или ядра.

**Sidecar-less Architecture (Архитектура без сайдкаров)** — подход в Service Mesh (например, Istio Ambient) и безопасности, использующий eBPF для перехвата и обработки трафика на уровне узла, что устраняет необходимость запуска дополнительных контейнеров (sidecars) в каждом поде и снижает потребление ресурсов на 50–70%.

**kube-proxy-replacement** — режим работы CNI (Cilium, Calico), при котором стандартный `kube-proxy` полностью заменяется eBPF-программами. Это обеспечивает производительность $O(1)$ для балансировки трафика сервисов любого масштаба.

**BPF Map** — структура данных ядра, используемая для обмена информацией между eBPF-программами и пользовательским пространством. В Kubernetes BPF Maps хранят состояния соединений, маршруты, политики и метрики.

## Основные концепции

Технологическая база eBPF (карты, верификатор, JIT) подробно описана в [**eBPF в Linux**](../../../../Linux/Core/kernel/ebpf.md).

### Точки подключения (Hooks) в Kubernetes

1.  **XDP (eXpress Data Path):** Работает на уровне драйвера сетевой карты. Применяется для защиты от DDoS и для Ingress-балансировки (Cilium Ingress).
2.  **TC (Traffic Control):** Гибкая точка для реализации NetworkPolicy и маршрутизации. Позволяет инспектировать пакеты как на входе, так и на выходе из veth-пары пода.
3.  **Socket-level Hooks (SOCKMAP/SOCKHASH):** Позволяют "сшивать" сокеты приложения и прокси-сервера (например, Envoy в Ambient Mesh) внутри ядра, минуя сетевой стек TCP/IP, что снижает задержки (latency) на 15–20%.
4.  **LSM Hooks (Linux Security Modules):** Используются в современных инструментах безопасности (Tetragon) для блокировки вредоносных действий (например, выполнение `execve` в недоверенном поде) на уровне ядра.

### Механизмы совместимости

*   **BTF (BPF Type Format) и CO-RE (Compile Once – Run Everywhere):** Позволяют запускать одни и те же eBPF-программы на разных версиях ядер без перекомпиляции на целевом узле.
*   **WASM Post-processing:** Использование WebAssembly для обработки событий из ядра в пользовательском пространстве (актуально для Inspektor Gadget).

### Сравнение технологий балансировки

| Характеристика | iptables | IPVS | eBPF (Cilium/Calico) |
| :--- | :--- | :--- | :--- |
| **Сложность поиска** | $O(n)$ — линейная | $O(1)$ — хэш-таблица | $O(1)$ — хэш-таблица |
| **Масштабируемость** | Низкая (деградация при >5k сервисов) | Высокая | Максимальная |
| **Обновление правил** | Полная перезагрузка (стоп-трафик) | Инкрементально | Мгновенно через BPF Maps |
| **Контекст** | Только сетевой пакет | L4 (IP/Port) | Полный контекст (Pod, Identity, L7) |

---

## Практические сценарии

### Предварительные требования

Перед развертыванием CNI на базе eBPF убедитесь, что инфраструктура соответствует требованиям.

#### Аппаратные требования

*   **Процессор:** x86_64 (Intel/AMD) или ARM64. Поддержка инструкций BMI/BMI2 желательна для JIT-компиляции.
*   **Сеть:** NIC с поддержкой драйверов, позволяющих XDP-режим (для полной функциональности).
*   **Память:** Минимум 4 GB RAM на узел; для кластеров >1000 подов рекомендуется 8+ GB (BPF Maps занимают невытесняемую память).

#### Программные требования

*   **Ядро Linux:**
    *   Минимум 5.10 для базового режима (kube-proxy replacement).
    *   Минимум 6.1+ для полноценной работы LSM, Ring Buffer и современных хуков.
    *   Рекомендуется 6.6+ LTS для production (стабильность BTF и CO-RE).
*   **Конфигурация ядра:**
    ```bash
    # Проверка обязательных параметров
    zgrep CONFIG_BPF /boot/config-$(uname -r)
    # → CONFIG_BPF=y
    # → CONFIG_BPF_SYSCALL=y
    # → CONFIG_BPF_JIT=y
    # → CONFIG_DEBUG_INFO_BTF=y (требуется для CO-RE)
    ```
*   **Файловая система BPF:**
    ```bash
    sudo mount | grep /sys/fs/bpf
    # → bpffs on /sys/fs/bpf type bpffs (rw,nosuid,nodev,noexec,relatime)
    ```
    При отсутствии монтирования:
    ```bash
    sudo mount -t bpf bpf /sys/fs/bpf
    ```
*   **Kubernetes:** Версия 1.28+ (рекомендуется 1.30+ для полной поддержки Gateway API и MCS API).
*   **Сетевые сервисы:** Отключение конфликтующих служб файервола (ufw, firewalld) и отключение swap.

#### Проверка совместимости ядра

```bash
# Версия ядра
uname -r

# Наличие bpffs
mount | grep bpf

# Доступные хуки eBPF
sudo bpftool feature probe
```

### Сетевая связность и Service Mesh

#### Cilium ClusterMesh и Gateway API

Cilium является эталонным решением, объединяющим CNI и Service Mesh.
*   **ClusterMesh:** Объединение кластеров в единую плоскую сеть с mTLS на базе eBPF (через ztunnel).
*   **Gateway API:** Нативная реализация стандарта [**Gateway API**](../../gateway_api/definitions.md) непосредственно в плоскости данных eBPF.
*   **Подробности:** См. [**Cilium: Высокопроизводительный CNI на базе eBPF**](./cilium.md).

#### Istio Ambient Mesh (GA)

В 2026 году Ambient Mesh стал основным режимом Istio.
*   **Механизм:** Использует eBPF для прозрачного перенаправления трафика в `ztunnel` (L4) и `waypoint proxy` (L7).
*   **Преимущество:** Полная безопасность mTLS и L7-управление без "налога на сайдкары" (sidecar tax).

### Развертывание CNI на базе eBPF (Cilium)

#### Шаг 1: Подготовка узлов

```bash
# Отключение swap (обязательно для Kubernetes)
sudo swapoff -a

# Остановка конфликтующих служб файервола
sudo systemctl stop ufw   # Debian/Ubuntu
# или
sudo systemctl stop firewalld  # RHEL/Rocky Linux

# Проверка версии ядра
uname -r
# → 6.1.0-18-amd64 (минимум 5.10 для kube-proxy replacement)

# Монтирование bpffs
sudo mount -t bpf bpf /sys/fs/bpf
```

#### Шаг 2: Установка через Helm

```bash
# Добавление репозитория
helm repo add cilium https://helm.cilium.io/
helm repo update

# Установка с заменой kube-proxy
helm upgrade --install cilium cilium/cilium \
  --namespace kube-system \
  --version 1.20.0 \
  --set kubeProxyReplacement=strict \
  --set k8sServiceHost=10.0.0.10 \
  --set k8sServicePort=6443 \
  --set l2announcements.enabled=true \
  --set externalIPs.enabled=true \
  --set gatewayAPI.enabled=true \
  --set bpf.masquerade=true
```

#### Шаг 3: Валидация установки

```bash
# Проверка статуса Cilium Agent на всех узлах
kubectl -n kube-system rollout status ds/cilium

# Общий статус
cilium status
# → ожидаемый результат: KVStore: Ok, Kubernetes: Ok, Cilium: Ok, Hubble: Ok

# Проверка замены kube-proxy
kubectl -n kube-system get pods -l k8s-app=kube-proxy
# → pods не должны существовать (strict mode)

# Проверка eBPF-программ на узле
sudo bpftool prog list | grep cilium
# → вывод списка загруженных программ Cilium
```

### Валидация сетевой связности

```bash
# Развертывание тестовых подов
kubectl apply -f https://k8s.io/examples/admin/dns/dnsutils.yaml

# Проверка DNS-резолвинга (внутренний DNS через CoreDNS)
kubectl exec -it dnsutils -- nslookup kubernetes.default
# → Address: 10.96.0.1

# Проверка pod-to-pod связности
kubectl exec -it dnsutils -- ping -c 3 10.244.0.1

# Проверка Service ClusterIP
kubectl exec -it dnsutils -- curl -s http://kubernetes.default
```

### Безопасность среды выполнения (Runtime Security)

Современные инструменты на базе eBPF перешли от простого обнаружения (Detection) к предотвращению (Prevention).

1.  **Tetragon (LSM Enforcement):** Блокирует запрещенные системные вызовы в реальном времени. Например, можно запретить запуск любых бинарных файлов, кроме одобренных, на уровне ядра.
    *   **Подробнее:** [**Безопасность в Runtime (Falco, Tetragon)**](../../../../Docker/Docker_security/runtime_monitoring.md).
2.  **Inspektor Gadget (OCI-based):** Инструмент для отладки, где eBPF-программы ("гаджеты") упакованы как OCI-образы. Позволяет трассировать сетевые запросы, доступ к файлам и сигналы в реальном времени.

### Наблюдаемость (Observability)

eBPF обеспечивает глубокую видимость без изменения кода приложения:
*   **Hubble:** Визуализация сетевых потоков в реальном времени, аудит NetworkPolicy и отслеживание L7-метрик (HTTP, gRPC, DB).
*   **Continuous Profiling:** Инструменты вроде Parca или Pyroscope используют eBPF для непрерывного профилирования CPU и памяти с оверхедом <1%. См. [**Continuous Profiling**](../../../../Concepts/continuous_profiling.md).

---

## Диагностика и устранение неполадок

Традиционные утилиты (`tcpdump`, `iptables-save`) часто не видят трафик, обработанный внутри eBPF. Для диагностики используются специализированные инструменты:

| Инструмент | Назначение |
| :--- | :--- |
| **bpftool** | Инспекция загруженных BPF-программ и содержимого BPF Maps. |
| **pwru** (Packet Where Are You) | Отслеживание пути пакета внутри ядра и поиск места "дропа" (kernel drops). |
| **gadget** | Набор инструментов Inspektor Gadget для трассировки системных вызовов и сети. |
| **cilium monitor** | Просмотр событий прохождения пакетов через фильтры Cilium. |
| **cilium bpf** | Прямой доступ к BPF Maps и программам через CLI Cilium. |

### Типичные проблемы и решения

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Pod не получает IP** | CNI плагин не работает; неверный CIDR | `kubectl describe pod <pod>`; `kubectl logs -n kube-system -l k8s-app=cilium` | Проверить CIDR pool; проверить конфиг CNI (`/etc/cni/net.d/`) |
| **kube-proxy не отключен** | `kubeProxyReplacement` не strict | `kubectl -n kube-system get pods -l k8s-app=kube-proxy` | Переустановить Helm-чарт с `kubeProxyReplacement=strict` и перезапустить DaemonSet |
| **BPF map full** | Недостаточный лимит памяти под карты | `dmesg | grep -i "bpf"`; `cilium bpf metrics list` | Увеличить `bpf-map-dynamic-size-ratio` или добавить RAM |
| **Потеря пакетов при MTU** | VXLAN инкапсуляция с неправильным MTU | `ip link show cilium_vxlan` | Установить MTU на 50 байт меньше физического интерфейса |
| **Hubble не видит трафик** | Hubble не включен или переполнен буфер | `cilium status`; `hubble observe` | Проверить `hubble.enabled=true`; увеличить `hubble.buffer-max-size` |
| **LSM политики не применяются** | Ядро без BTF или Tetragon не установлен | `sudo bpftool feature probe | grep lsm` | Обновить ядро; проверить `CONFIG_BPF_LSM=y` |

### Пример диагностики дропа пакета

```bash
# Отслеживание дропов в реальном времени через Hubble
hubble observe --type drop --follow -n production

# Поиск конкретной функции ядра через pwru
sudo pwru --filter-dst-port 80 --output-tuple
# → показывает функцию ядра (например, bpf_lxc_netpolicy), где произошел дроп

# Инспекция BPF Maps Cilium
cilium bpf ct list global
cilium bpf policy get <endpoint-id>
```

---

## Рекомендации и очистка

### Рекомендации для production

1.  **Всегда используйте `kubeProxyReplacement=strict`:** Это гарантирует полное удаление kube-proxy и исключает конфликты между iptables и eBPF-программами.
2.  **Включите подписанные OCI-гаджеты:** Вместо загрузки произвольных eBPF-программ используйте подписанные OCI-образы для контроля доверия.
3.  **Настройте лимиты BPF Maps заранее:** В кластерах >500 узлов настройте `bpf-map-dynamic-size-ratio` до обновления production.
4.  **Используйте `native-routing` при наличии BGP:** Исключает накладные расходы инкапсуляции и упрощает отладку.
5.  **Мониторинг Hubble как источника истины:** Hubble является первичным источником данных о сетевых событиях; интегрируйте его с Prometheus/Grafana для алертинга.
6.  **Приоритет nftables для CNI без eBPF:** Если eBPF недоступен (устаревшее ядро), используйте nftables вместо iptables для атомарной загрузки правил.

### Очистка среды

```bash
# Полное удаление Cilium через Helm
helm uninstall cilium -n kube-system

# Удаление CRD (если не используются другие компоненты)
kubectl delete crd ciliumendpoints.cilium.io ciliumclusterwidenetworkpolicies.cilium.io ...

# Очистка iptables правил, оставшихся после удаления
sudo iptables-save | grep -v CILIUM | sudo iptables-restore

# Проверка отсутствия eBPF-программ
sudo bpftool prog list | grep -i cilium
# → вывод должен быть пустым
```

---

## Крайние случаи и ограничения

1.  **Использование памяти:** BPF-карты (Maps) занимают невытесняемую память ядра. В кластерах 100k+ подов требуется тщательное планирование ресурсов и мониторинг через `cilium bpf metrics list`.
2.  **Привилегированный доступ:** Загрузка eBPF-программ требует `CAP_SYS_ADMIN` или `CAP_BPF` в ядре. В продакшн-средах используйте минимально возможные привилегии.
3.  **Совместимость с ядром:** eBPF-программы, скомпилированные для одного ядра, могут не работать на другом без CO-RE/BTF. Всегда проверяйте `CONFIG_DEBUG_INFO_BTF=y` на целевых узлах.
4.  **Сетевые политики и L7-инспекция:** L7-фильтрация (HTTP, gRPC) работает только для незашифрованного трафика или при явном терминировании TLS на прокси. Для HTTPS без терминации Cilium видит только SNI.
5.  **Внутриузловой трафик:** При использовании WireGuard или IPsec шифруется только межузловой трафик. Трафик между подами на одной ноде по умолчанию не шифруется.
6.  **Ограничения отладки:** eBPF работает на уровне ядра. Стандартные утилиты (`tcpdump`, `strace`) не видят внутренние преобразования пакетов в BPF Maps. Требуется специализированный стек (`bpftool`, `cilium monitor`, `pwru`).
7.  **Ограничения по версии ядра:** При обновлении ядра без сохранения BTF (например, кастомный билд) все CO-RE-программы потребуют перекомпиляции и перезагрузки Cilium Agent.

---

## Дополнительные сведения

### Системные требования (2026)

| Режим | Ядро (Min) | Рекомендуемое ядро (2026) |
| :--- | :--- | :--- |
| **Базовый (Networking)** | 5.10+ | 5.15+ |
| **Advanced (LSM, CO-RE)** | 5.10+ | 6.1+ |
| **Optimal** | 5.15+ | 6.6+ (LTS) |

### См. также

- [**Cilium: Высокопроизводительный CNI**](./cilium.md) — детальный разбор лидера рынка.
- [**Сравнение режимов kube-proxy**](../cni_kube_proxy_roles.md) — когда выбирать eBPF.
- [**Путь трафика в Kubernetes**](../traffic_path.md) — схемы прохождения пакетов.
- [**eBPF в Linux (Общая технология)**](../../../../Linux/Core/kernel/ebpf.md) — фундаментальные основы.
- [**Безопасность в Runtime (Falco, Tetragon)**](../../../../Docker/Docker_security/runtime_monitoring.md) — защита среды выполнения.
