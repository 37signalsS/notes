# eBPF в Kubernetes: Замена kube-proxy

## Определения

**eBPF (Extended Berkeley Packet Filter)** — технология в ядре Linux, позволяющая запускать пользовательские программы в изолированной среде непосредственно в пространстве ядра (`kernel space`) без необходимости переключения контекста в пользовательское пространство (`user space`).

**eBPF для сети Kubernetes** — использование eBPF-программ для реализации функций сетевого стека кластера: балансировки нагрузки (замена `kube-proxy`), фильтрации трафика (замена `iptables`), наблюдения за сетевыми событиями.

## Основные концепции

### Принцип работы eBPF в сети

В контексте сети eBPF позволяет "прикреплять" программы к различным точкам (хукам) в сетевом стеке ядра, где они могут с высокой скоростью проверять, изменять или отбрасывать сетевые пакеты.

### Преимущества eBPF в Calico

| Преимущество | Описание |
|--------------|----------|
| **Высокая производительность** | Обработка пакетов на уровне ядра снижает задержки и нагрузку на CPU по сравнению с `iptables` или `ipvs` |
| **Замена `kube-proxy`** | Calico в режиме eBPF полностью берёт на себя функции `kube-proxy`, включая DNAT для сервисов |
| **Эффективные сетевые политики** | Правила `NetworkPolicy` реализуются через eBPF, что работает быстрее, чем `iptables` |

### Недостатки eBPF

| Недостаток | Описание |
|------------|----------|
| **Сложность отладки** | Требует специальных знаний и инструментов (например, `bpftool`) |
| **Требования к ядру** | Требуется ядро Linux 4.19+ с поддержкой eBPF |
| **Избыточность для малых нагрузок** | Если существующая подсистема справляется, переход на eBPF может быть излишним усложнением |

---

## Практические сценарии

### Установка Calico с eBPF (новый кластер)

> **Внимание:** Команды и конфигурации являются примером. Сверяйтесь с официальной документацией Calico для актуальных версий манифестов.

Миграция существующего кластера на eBPF — сложная процедура. Рекомендуется установка нового кластера сразу в режиме eBPF.

#### Шаг 1: Инициализация кластера без `kube-proxy`

```bash
sudo kubeadm init --skip-phases=addon/kube-proxy
```

#### Шаг 2: Подготовка манифеста Calico

1. Скачайте официальный манифест `calico.yaml` с сайта проекта Calico.
2. **Настройте `podCIDR`**: Убедитесь, что `CALICO_IPV4POOL_CIDR` соответствует `pod-network-cidr` при инициализации.
3. **Включите VXLAN** для совместимости и производительности:

    ```yaml
    # В ConfigMap 'calico-config'
    - name: CALICO_IPV4POOL_IPIP
      value: "Never"
    - name: CALICO_IPV4POOL_VXLAN
      value: "Always"
    ```

#### Шаг 3: Развертывание Calico

```bash
kubectl apply -f calico.yaml
```

#### Шаг 4: Включение режима eBPF

Создайте ресурс `FelixConfiguration`:

```yaml
# felix-config.yaml
apiVersion: projectcalico.org/v3
kind: FelixConfiguration
metadata:
  name: default
spec:
  bpfEnabled: true
```

Примените конфигурацию:

```bash
calicoctl apply -f felix-config.yaml
# или
kubectl apply -f felix-config.yaml
```

### Диагностика и проверка

| Проверка | Команда | Ожидаемый результат |
|----------|---------|---------------------|
| **Отсутствие `kube-proxy`** | `kubectl get pods -n kube-system \| grep kube-proxy` | Нет подов `kube-proxy` |
| **Отсутствие `ipvs`** | `ip addr show \| grep kube-ipvs0` | Интерфейс не найден |
| **Монтирование BPF** | `mount \| grep bpf` | `none on /sys/fs/bpf type bpf (rw,relatime)` |
| **NAT-таблица eBPF** | `kubectl exec -it -n kube-system <calico-node-pod> -- calico-node bpf nat dump` | Вывод NAT-правил |

---

## Дополнительные сведения

**См. также:**
- Режимы работы `kube-proxy` (iptables, IPVS) — [CNI и kube-proxy: определения](./definitions.md#режимы-работы-kube-proxy)
- Фильтрация трафика между подами — [NetworkPolicy](../NetworkPolicy/network_policy.md)
- Оптимизация DSR через eBPF — [CNI: Выбор плагина и внешние типы доступа](./selection_and_external_access.md#direct-service-return-dsr-через-ebpf)
