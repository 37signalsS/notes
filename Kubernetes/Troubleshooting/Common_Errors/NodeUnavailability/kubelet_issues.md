# Недоступность узла: Проблемы Kubelet

## Основные определения

**Сбой Kubelet** (Kubelet Issue) — критическое состояние, при котором агент `kubelet` на узле не может выполнять свои функции (управление контейнерами, отчетность о состоянии узла, выполнение liveness-проб). Это приводит к переходу узла в статус `NotReady` (если агент жив, но сообщает об ошибке) или `Unknown` (если агент не отвечает).

**Kubelet** — основной системный агент Kubernetes, работающий на каждом узле кластера. Он является «связующим звеном» между API-сервером и средой выполнения контейнеров (CRI).

Подробное описание архитектуры агента: [Обзор Kubelet](../../../Concepts/kubelet.md).

## Основные концепции

### Критические зависимости Kubelet

Для стабильной работы агенту необходимы:
- **Связность с API-сервером**: Доступ по порту `6443` и валидные сертификаты в `kubeconfig`.
- **Работоспособный CRI**: Связь через Unix-сокет (например, `/run/containerd/containerd.sock`).
- **Корректный Cgroup Driver**: Совпадение драйвера в `kubelet` и в CRI (обычно `systemd`).
- **Ресурсы ОС**: Достаточное количество RAM, CPU и свободных PID.

### Точки отказа и диагностические файлы

| Объект | Путь в ОС | Назначение |
| :--- | :--- | :--- |
| **Файл конфигурации** | `/var/lib/kubelet/config.yaml` | Основные параметры (KubeletConfiguration). |
| **Kubeconfig** | `/etc/kubernetes/kubelet.conf` | Реквизиты доступа к API-серверу. |
| **Сертификаты** | `/var/lib/kubelet/pki/` | Клиентские сертификаты узла. |
| **Файлы состояния** | `/var/lib/kubelet/cpu_manager_state` | Данные о выделении ресурсов (могут повреждаться). |
| **Журнал (Logs)** | `journalctl -u kubelet` | Основной поток системных сообщений. |

## Практические сценарии

### Сценарий 1: Процесс Kubelet падает или не запускается

**Симптомы**: Узел в статусе `Unknown`, сервис `kubelet` имеет статус `failed` или `activating`.

**Диагностика**:
```bash
# 1. Проверка статуса сервиса
systemctl status kubelet
# → Active: failed (Result: exit-code)

# 2. Поиск конкретной причины падения
journalctl -u kubelet -n 50 --no-pager
```

**Распространённые причины**:
- **Несоответствие cgroup driver**: `kubelet` ожидает `systemd`, а рантайм настроен на `cgroupfs`.
- **Повреждение файлов состояния**: Если в логах есть ошибки про `cpu_manager`, попробуйте:
  ```bash
  rm /var/lib/kubelet/cpu_manager_state
  systemctl restart kubelet
  ```
- **Ошибка в YAML**: Невалидный синтаксис в `/var/lib/kubelet/config.yaml`.

### Сценарий 2: Ошибки взаимодействия с CRI (Container Runtime)

**Симптомы**: Узел `NotReady`, в логах ошибки `CRI: container runtime is down` или `failed to connect to socket`.

**Диагностика**:
```bash
# 1. Проверка сокета через crictl
crictl info
# → Ошибка, если рантайм недоступен

# 2. Проверка статуса containerd/CRI-O
systemctl status containerd
```

**Решение**:
Перезапустите рантайм и проверьте права доступа к сокету. Подробнее: [Проблемы рантайма](./runtime_issues.md).

### Сценарий 3: Истечение сертификатов узла

**Симптомы**: `kubelet` не может авторизоваться, ошибки `x509: certificate has expired`.

**Диагностика**:
```bash
# Проверка срока действия сертификата в kubeconfig
openssl x509 -in /var/lib/kubelet/pki/kubelet-client-current.pem -text -noout | grep -A 2 "Validity"
# → Not After : Jul 20 2026 ...
```

**Решение**:
Если используется `kubeadm`, выполните:
```bash
kubeadm certs renew all
systemctl restart kubelet
```
*Примечание: Убедитесь, что включена опция `serverTLSBootstrap: true` в конфиге для автоматического продления в будущем.*

### Сценарий 4: Проблемы с обновлением Node Lease

**Симптомы**: `kubelet` работает, `crictl ps` показывает запущенные контейнеры, но узел в статусе `Unknown`.

**Причина**: `kubelet` не может отправить heartbeats (объекты Lease) в API-сервер из-за сетевых блокировок или перегрузки Control Plane.

**Диагностика**:
```bash
# Проверка связности с API-сервером
curl -k https://<api-server-endpoint>:6443/healthz
# → ok
```

## Дополнительная информация

### Смежные разделы
- [Обслуживание сертификатов](../../../Operations/certificate_management.md) — детали ротации и CSR.
- [Диагностика узла](./diagnostics.md) — общий алгоритм поиска проблем.
- [Давление ресурсов](./resource_pressure.md) — влияние OOM и дефицита ресурсов на `kubelet`.

### Полезные инструменты
- **`crictl`** — CLI для инспекции контейнеров напрямую через CRI.
- **`journalctl -u kubelet -f`** — просмотр логов в реальном времени.
