# Недоступность узла: Проблемы среды выполнения (Runtime)

## Определения

**Среда выполнения контейнеров (Container Runtime)** — низкоуровневое программное обеспечение, отвечающее за запуск и управление жизненным циклом контейнеров на узле. Kubernetes взаимодействует со средой выполнения через стандартный интерфейс **CRI (Container Runtime Interface)**.

**Сбой CRI (CRI Failure)** — критическая ситуация, при которой агент `kubelet` теряет возможность подключения к среде выполнения (containerd, CRI-O). Это приводит к невозможности управления подами и переходу узла в статус `NotReady`.

## Основные концепции

### Поддерживаемые среды выполнения

| Runtime | Статус | Примечание |
|:--------|:-------|:-----------|
| **containerd** | По умолчанию (с K8s 1.24+) | Стандарт de facto после удаления dockershim. |
| **CRI-O** | Поддерживается | Легковесная альтернатива, ориентированная на Kubernetes. |
| **Docker Engine** | Устарел (Deprecated) | Удален из состава Kubernetes начиная с версии 1.24. |

### Взаимодействие Kubelet и Runtime

| Компонент | Сокет (Socket) | Назначение |
|:----------|:---------------|:-----------|
| **containerd** | `/run/containerd/containerd.sock` | Интерфейс CRI для kubelet. |
| **CRI-O** | `/run/crio/crio.sock` | Интерфейс CRI для kubelet. |
| **crictl** | — | CLI-утилита для диагностики сред выполнения через CRI. |

### Типичные причины сбоев

| Сбой | Причина | Симптом |
|:-----|:--------|:--------|
| Остановка процесса | Crash, OOM (Out of Memory) | Ошибка `failed to connect to containerd`. |
| Ошибка конфигурации | Опечатки в `config.toml` | Runtime не запускается после рестарта. |
| Проблемы с сертификатами | TLS для приватных реестров | Ошибка `x509: certificate has expired`. |
| Недоступен Sandbox image | Проблемы с сетью или зеркалом | Поды зависают в статусе `ContainerCreating`. |

### Диагностические команды

| Команда | Назначение |
|:--------|:-----------|
| `systemctl status containerd` | Проверка статуса системной службы containerd. |
| `crictl info` | Получение информации о состоянии рантайма. |
| `crictl ps` | Список работающих контейнеров через CRI. |
| `crictl pods` | Просмотр состояния sandbox-подов. |
| `journalctl -u containerd -f` | Просмотр логов containerd в реальном времени. |

## Практические сценарии

### Сценарий 1: containerd не отвечает или остановлен

**Симптомы:**

- `kubelet` не может запускать или удалять контейнеры.
- В логах `kubelet` фиксируются ошибки `failed to connect to containerd`.
- Узел находится в статусе `NotReady`.

**Диагностика:**

```bash
# Проверка статуса службы
systemctl status containerd

# Анализ системного журнала
journalctl -u containerd -n 100 --no-pager

# Проверка доступности сокета
ls -la /run/containerd/containerd.sock

# Проверка отклика через crictl
crictl info
```

**Решение:**

```bash
# Перезапуск службы
sudo systemctl restart containerd

# Проверка статуса после перезапуска
crictl info
kubectl get nodes
```

### Сценарий 2: Ошибка в конфигурации containerd

**Симптомы:**

- Служба containerd не запускается (`systemctl status` показывает `failed`).
- В логах присутствуют ошибки синтаксиса или парсинга файла конфигурации.

**Диагностика:**

```bash
# Проверка содержимого файла конфигурации
cat /etc/containerd/config.toml

# Валидация текущей конфигурации (containerd 1.6+)
containerd config dump | head -n 50
```

**Решение:**

1. Восстановите конфигурацию из бэкапа или сгенерируйте дефолтную:

   ```bash
   sudo cp /etc/containerd/config.toml /etc/containerd/config.toml.bak
   sudo containerd config default | sudo tee /etc/containerd/config.toml
   ```

2. Убедитесь в наличии критических настроек для Kubernetes:
   - `SystemdCgroup = true` (обязательно для интеграции с cgroups v2).
   - Корректный путь к `sandbox_image` (например, `registry.k8s.io/pause:3.9`).
   - При необходимости — `Rlimits` для лимита файловых дескрипторов всех контейнеров:
     ```toml
     [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc.options]
       Rlimits = [
         { type = "RLIMIT_NOFILE", hard = 1048576, soft = 1048576 }
       ]
     ```
3. Перезапустите службу: `sudo systemctl restart containerd`.

### Сценарий 3: Проблемы с Sandbox (pause) контейнерами

**Симптомы:**

- Поды зависают в статусе `ContainerCreating`.
- В событиях (Events) пода отображается ошибка `Failed to create sandbox`.

**Диагностика:**

```bash
# Проверка наличия pause-образов в локальном хранилище
crictl images | grep pause

# Проверка настроенного sandbox_image в конфигурации
containerd config dump | grep sandbox_image
```

**Решение:**

1. Принудительно загрузите актуальный образ паузы:

   ```bash
   crictl pull registry.k8s.io/pause:3.9
   ```

2. Если проблема вызвана "осиротевшими" sandbox-контейнерами, выполните их очистку:

   ```bash
   crictl rmp -fa
   ```

3. Перезапустите рантайм: `sudo systemctl restart containerd`.

## Дополнительная информация

### Смежные разделы по диагностике

- [Чек-лист диагностики](./diagnostics.md) — общая процедура проверки узла.
- [Проблемы Kubelet](./kubelet_issues.md) — зависимость агента от CRI.
- [Давление на ресурсы](./resource_pressure.md) — очистка диска от неиспользуемых образов.

### Полезные ссылки

- [Документация containerd по началу работы](https://github.com/containerd/containerd/blob/main/docs/getting-started.md)
- [Проект CRI-O](https://cri-o.io/)
- [Удаление dockershim в Kubernetes 1.24](https://kubernetes.io/blog/2022/02/17/dockershim-faq/)
