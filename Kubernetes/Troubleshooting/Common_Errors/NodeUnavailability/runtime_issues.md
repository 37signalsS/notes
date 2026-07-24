# Недоступность узла: Проблемы среды выполнения (Runtime)

## Основные определения

**Среда выполнения контейнеров (Container Runtime)** — низкоуровневое программное обеспечение, отвечающее за запуск и управление жизненным циклом контейнеров на узле. Kubernetes взаимодействует со средой выполнения через стандартный интерфейс **CRI (Container Runtime Interface)**.

**Сбой CRI (CRI Failure)** — критическое состояние, при котором агент `kubelet` теряет связь со средой выполнения (containerd, CRI-O) или рантайм сообщает о внутренней ошибке. Это приводит к невозможности запуска новых подов и остановке обновления статуса существующих, в результате чего узел переходит в статус `NotReady`.

## Основные концепции

### Актуальные среды выполнения

С версии Kubernetes 1.24 поддержка Docker Engine (через dockershim) удалена. Современные кластеры используют прямые реализации CRI:

| Runtime | Статус | Примечание |
| :--- | :--- | :--- |
| **containerd** | Стандарт (рекомендуется) | Отраслевой стандарт. Используется в большинстве облачных и bare-metal инсталляций. |
| **CRI-O** | Альтернатива | Облегчённый рантайм, разработанный специально для Kubernetes. |

### Взаимодействие и диагностика

| Компонент | Путь / Сокет | Назначение |
| :--- | :--- | :--- |
| **containerd** | `/run/containerd/containerd.sock` | Unix-сокет для взаимодействия с `kubelet`. |
| **CRI-O** | `/run/crio/crio.sock` | Unix-сокет для взаимодействия с `kubelet`. |
| **`crictl`** | `/usr/local/bin/crictl` | CLI-утилита для прямой отладки CRI (не зависит от API-сервера). |

**Важно:** Для работы `crictl` необходимо настроить путь к сокету в `/etc/crictl.yaml`:
```yaml
runtime-endpoint: unix:///run/containerd/containerd.sock
image-endpoint: unix:///run/containerd/containerd.sock
```

### Критические точки отказа

1.  **Несоответствие драйвера Cgroups**: Если `kubelet` и рантайм настроены на разные драйверы (`systemd` vs `cgroupfs`), запуск контейнеров будет невозможен.
2.  **Зависание `runc`**: Сбои на уровне ядра или дефицит ресурсов могут привести к зависанию процессов `runc`, что блокирует создание новых контейнеров.
3.  ** Sandbox Image (pause-контейнер)**: Отсутствие доступа к образу `pause` (используется как сетевой фундамент пода) блокирует переход подов в статус `Running`.

## Практические сценарии

### Сценарий 1: containerd не отвечает или падает

**Симптомы**: Узел `NotReady`, в логах `kubelet` ошибки `failed to connect to cri: ... connection refused`.

**Диагностика**:
```bash
# 1. Проверка системного юнита
systemctl status containerd
# → Active: failed (или постоянно перезагружается)

# 2. Анализ логов на предмет OOM или ошибок плагинов
journalctl -u containerd -n 100 --no-pager

# 3. Проверка отклика через CRI API
crictl info
# → Ошибка соединения, если сокет недоступен
```

**Решение**:
```bash
sudo systemctl restart containerd
```
*Если не помогает, проверьте наличие свободных PID на узле (`cat /proc/sys/kernel/pid_max`) и дисковое пространство в `/var/lib/containerd`.*

### Сценарий 2: Ошибка «SystemdCgroup» (Cgroups v2)

**Симптомы**: `containerd` запущен, но поды не стартуют. В логах `kubelet`: `Failed to create pod sandbox: rpc error: code = Unknown desc = failed to create containerd task: ... failed to create shim task: OCI runtime create failed`.

**Причина**: На современных дистрибутивах (Ubuntu 22.04+, RHEL 9) используется Cgroups v2, требующая настройки `SystemdCgroup = true`.

**Диагностика**:
```bash
# Проверка текущей конфигурации
containerd config dump | grep SystemdCgroup
# → SystemdCgroup = false (если это причина сбоя)
```

**Решение**:
Отредактируйте `/etc/containerd/config.toml`:
```toml
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc.options]
  SystemdCgroup = true
```
Затем перезапустите: `sudo systemctl restart containerd`.

### Сценарий 3: Проблемы с Sandbox-образом (pause)

**Симптомы**: Поды «зависают» в `ContainerCreating`. В событиях `kubectl describe pod`: `Failed to pull image "registry.k8s.io/pause:3.10"`.

**Диагностика**:
```bash
# Проверка настроенного пути к образу
containerd config dump | grep sandbox_image
# → sandbox_image = "registry.k8s.io/pause:3.10"
```

**Решение**:
1.  Принудительно скачайте образ: `crictl pull registry.k8s.io/pause:3.10`.
2.  Если кластер находится в изолированной сети (air-gapped), убедитесь, что образ доступен в локальном реестре и путь в `config.toml` скорректирован.

### Сценарий 4: Очистка зависших ресурсов рантайма

**Симптомы**: Узел переполнен «зомби-контейнерами» или sandbox-ами, которые не удаляются через `kubectl`.

**Решение (с осторожностью)**:
```bash
# Список всех подов в рантайме
crictl pods

# Принудительное удаление всех неиспользуемых подов (sandbox)
crictl rmp -fa
```

## Дополнительная информация

### Смежные разделы
- [Проблемы Kubelet](./kubelet_issues.md) — зависимость агента от CRI.
- [Диагностика узла](./diagnostics.md) — общие шаги проверки.
- [Давление ресурсов](./resource_pressure.md) — очистка образов (`crictl rmi --prune`).

### Полезные ссылки
- [Документация containerd (CRI)](https://github.com/containerd/containerd/blob/main/docs/cri/config.md)
- [Проект CRI-O: Руководство по отладке](https://cri-o.io/)
