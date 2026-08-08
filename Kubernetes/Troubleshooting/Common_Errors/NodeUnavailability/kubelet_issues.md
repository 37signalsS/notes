# Недоступность узла: Проблемы Kubelet

Агент `kubelet` является критическим компонентом, обеспечивающим связь между API-сервером и рантаймом контейнеров. Его сбой или некорректная настройка — самая частая причина перехода узла в состояния `NotReady` или `Unknown`.

## Основные определения

**Сбой Kubelet (Kubelet Issue)** — состояние, при котором агент не может выполнять жизненно важные функции: управление контейнерами (CRI), отчетность о состоянии (Heartbeats), выполнение проб (Probes) и управление ресурсами (Cgroups/Volumes).

**Статусы при сбоях:**
- **`NotReady`**: Kubelet запущен, но сообщает о внутренней ошибке (например, `NetworkUnavailable`, `DiskPressure` или сбой CNI).
- **`Unknown`**: Kubelet не отправляет данные в API-сервер (процесс упал, завис или изолирован сетевым экраном).

Подробная архитектура агента: [Обзор Kubelet](../../../Concepts/kubelet.md).

## Основные концепции

### Критические зависимости и точки отказа

| Компонент | Требование / Зависимость | Последствие сбоя |
| :--- | :--- | :--- |
| **Связность с API** | Порт `6443` (Outbound), валидный `kubelet.conf` | Статус `Unknown`, невозможность запустить поды |
| **CRI Runtime** | Доступ к Unix-сокету (containerd/CRI-O) | Статус `NotReady`, ошибка PLEG |
| **Cgroup Driver** | Совпадение (`systemd` vs `cgroupfs`) | Kubelet не запускается (Panic) |
| **Ресурсы ОС** | Свободная память, CPU и лимиты PID (`pid_max`) | Зависание агента, OOM-kill процесса `kubelet` |

### Файловая структура и файлы состояния

| Путь | Назначение |
| :--- | :--- |
| `/var/lib/kubelet/config.yaml` | Основная конфигурация (`KubeletConfiguration`). |
| `/etc/kubernetes/kubelet.conf` | Kubeconfig для авторизации узла в API-сервере. |
| `/var/lib/kubelet/pki/` | Сертификаты узла (клиентские и серверные). |
| `/var/lib/kubelet/cpu_manager_state` | Данные о выделении ядер (могут повреждаться). |
| `/var/lib/kubelet/memory_manager_state` | Данные о выделении памяти (NUMA). |

## Практические сценарии

### Сценарий 1: Kubelet не запускается (Cgroup Driver / YAML)

**Симптом**: Сервис `failed`, в логах: `misconfiguration: kubelet cgroup driver: "systemd" is different from docker cgroup driver: "cgroupfs"`.

**Диагностика и решение**:
1. Проверьте драйвер в конфиге Kubelet: `grep cgroupDriver /var/lib/kubelet/config.yaml`.
2. Проверьте драйвер в рантайме (например, `/etc/containerd/config.toml` -> `SystemdCgroup = true`).
3. **Важно:** В современных системах (cgroup v2) всегда используйте `systemd`. После правки:
   ```bash
   systemctl restart containerd kubelet
   ```

### Сценарий 2: Повреждение файлов состояния (State Corruption)

**Симптом**: Kubelet падает с ошибкой в `cpu_manager` или не может запустить поды с гарантированным QoS.

**Решение**:
Если файлы состояния повреждены или не соответствуют текущей конфигурации ядер, их можно безопасно удалить (Kubelet пересоздаст их при старте):
```bash
systemctl stop kubelet
rm /var/lib/kubelet/cpu_manager_state
rm /var/lib/kubelet/memory_manager_state
systemctl start kubelet
```

### Сценарий 3: Истечение сертификатов узла

**Симптом**: Ошибки `x509: certificate has expired` или `Unauthorized` в `journalctl`.

**Диагностика**:
Проверьте срок действия клиентского сертификата:
```bash
openssl x509 -in /var/lib/kubelet/pki/kubelet-client-current.pem -text -noout | grep -A 2 "Validity"
```

**Решение**:
1. Если используется `kubeadm`, обновите сертификаты: `kubeadm certs renew all`.
2. Для автоматизации включите `serverTLSBootstrap: true` в `/var/lib/kubelet/config.yaml`.
3. Если сертификаты уже просрочены, удалите файлы в `/var/lib/kubelet/pki/` и перезапустите агент — он создаст новый CSR (при наличии разрешающих RBAC правил в кластере).

### Сценарий 4: Ошибки PLEG (PLEG is unhealthy)

**Симптом**: Узел `NotReady`, логи забиты сообщениями `PLEG is unhealthy: relist period was too long`.

**Причины и отладка**:
- **Перегрузка CRI**: Проверьте `sudo crictl pods`. Если команда виснет — рантайм не отвечает.
- **I/O Wait**: Если диск системного раздела занят на 100%, Kubelet не может записать статус.
- **Решение**: Перезапуск рантайма (`systemctl restart containerd`) часто помогает как временная мера, но требует расследования причин зависания I/O.

### Сценарий 5: Поддержка Swap (Kubernetes 1.31+)

**Симптом**: Kubelet падает на узле с включенным Swap, хотя в 1.31 заявлена поддержка.

**Решение**:
Для работы со Swap необходимо явно настроить поведение в `KubeletConfiguration`:
```yaml
failSwapOn: false
memorySwap:
  swapBehavior: LimitedSwap
```
Без этих параметров Kubelet по умолчанию требует `swapoff -a`.

## Дополнительная информация

### Полезные команды диагностики
- `journalctl -u kubelet -f` — логи в реальном времени.
- `kubectl get node <name> -o yaml` — просмотр `status.conditions`.
- `crictl info` — проверка связности Kubelet <-> Runtime.

### Смежные разделы
- [Диагностика узла](./diagnostics.md) — системный алгоритм поиска проблем.
- [Проблемы рантайма](./runtime_issues.md) — если причина в `containerd`/`CRI-O`.
- [Давление ресурсов](./resource_pressure.md) — влияние Memory/Disk Pressure.
- [Управление сертификатами](../../../Operations/certificate_management.md) — детали ротации.
