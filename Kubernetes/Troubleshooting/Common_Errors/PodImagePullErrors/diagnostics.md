# Диагностика ошибок загрузки образов (Image Pull Errors)

## Определения

Основные понятия и термины процесса загрузки образов (Image Pull) приведены в разделе [Определения](./definitions.md).

---

## Основные концепции

### Стратегия диагностики

Диагностика выполняется по принципу «от простого к сложному»:

1. **kubectl describe pod** — анализ событий (Events) для определения типа ошибки.
2. **Проверка имени и тега** — существует ли манифест в реестре.
3. **Проверка imagePullSecrets** — корректна ли аутентификация.
4. **Проверка сети и DNS** — доступен ли реестр с узлов кластера.
5. **Проверка реестра** — логирование на стороне Registry, Rate Limit, настройки TLS.

### Ключевые поля в выводе kubectl describe

| Поле | Описание | Значение для анализа |
| :--- | :--- | :--- |
| `Events[].Reason` | Причина события | `Failed`, `BackOff` |
| `Events[].Message` | Детальное описание | Конкретная ошибка (`manifest not found`, `unauthorized`) |
| `Events[].Count` | Количество повторов | Частота возникновения |
| `ContainerStatuses[].State.Waiting.Reason` | Статус контейнера | `ImagePullBackOff`, `ErrImagePull` |

---

## Практические сценарии

### Сценарий 1: Анализ событий Pod

Первым шагом всегда является проверка событий пода:

```bash
kubectl describe pod <pod-name>
```

**Пример вывода в разделе `Events`:**

```text
Type     Reason     Age                From               Message
----     ------     ----               ----               -------
Warning  Failed     2m (x4 over 3m)    kubelet            Failed to pull image "my-app:1.1": rpc error: code = Unknown desc = Error response from daemon: manifest for my-app:1.1 not found
Warning  Failed     2m (x4 over 3m)    kubelet            Error: ErrImagePull
Normal   BackOff    1m (x6 over 2m)    kubelet            Back-off pulling image "my-app:1.1"
Warning  Failed     1m (x6 over 2m)    kubelet            Error: ImagePullBackOff
```

**Интерпретация:**

- `ErrImagePull` — разовая ошибка при попытке скачивания.
- `ImagePullBackOff` — переход в режим ожидания с экспоненциальной задержкой после нескольких неудач.

### Сценарий 2: Проверка имени и доступности образа

Если ошибка указывает на отсутствие манифеста (`manifest not found`), проверьте точное имя и наличие образа:

```bash
# Извлечение имени образа из спецификации пода
kubectl get pod <pod-name> -o jsonpath='{.spec.containers[*].image}'

# Проверка скачивания через локальный docker/podman
docker pull <image-name>

# Проверка без docker daemon (с использованием crane)
crane digest <image-name>
# → sha256:abc123... (если образ доступен)
```

### Сценарий 3: Проверка imagePullSecrets

Если ошибка указывает на отсутствие авторизации (`unauthorized` или `access denied`), проверьте секреты:

```bash
# Проверка наличия secret в спецификации пода
kubectl get pod <pod-name> -o jsonpath='{.spec.imagePullSecrets}'

# Проверка существования и типа секрета
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.type}'
# → kubernetes.io/dockerconfigjson

# Декодирование содержимого для проверки (внимательно!)
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d

# Проверка даты создания секрета (токены могут протухать)
kubectl get secret <secret-name> -n <namespace> -o yaml | grep creationTimestamp

# Проверка событий на ошибки аутентификации
kubectl get events --sort-by='.lastTimestamp' | grep -i secret
```

### Сценарий 4: Проверка сети и DNS с узла

Если возникают ошибки таймаута (`connection timed out`) или разрешения имен (`no such host`):

```bash
# Проверка разрешения DNS
ssh <node-name> "nslookup registry.example.com"

# Проверка доступности порта (443)
ssh <node-name> "curl -v telnet://registry.example.com:443"

# Проверка TLS-рукопожатия и сертификата
ssh <node-name> "curl -v https://registry.example.com/v2/"
```

**Проверка DNS изнутри кластера через временный под:**

```bash
kubectl run dns-test --image=busybox:1.28 --rm -it --restart=Never -- nslookup registry.example.com
```

Для глубокой диагностики сетевых правил и прокси обратитесь к разделу [Сетевые проблемы](./network_issues.md).

**Проверка с конкретной ноды:**
Если ошибка возникает только на одной ноде, узнайте её имя из `kubectl describe pod`, затем проверьте доступность registry напрямую с неё:

```bash
# Узнать ноду, на которой запущен pod
kubectl get pod <pod-name> -o wide

# SSH на ноду и ручной pull
ssh <node-name>
crictl pull registry.example.com/my-app:1.0
# или
docker pull registry.example.com/my-app:1.0
```

### Сценарий 5: После ребута ноды — перезапись плавающего тега

**Симптом:** После перезагрузки узла поды уходят в `ImagePullBackOff`, хотя до ребута работали и registry доступен.

**Причина:** Используется плавающий тег (`:latest` или `:dev`). Локальный кэш образов сброшен после ребута, kubelet пытается скачать образ заново. Если тег уже перезаписан сломанным образом, pull завершается ошибкой (`manifest not found`).

**Диагностика:**

```bash
kubectl describe pod <pod-name> | grep -A5 "Failed to pull image"
# → manifest for my-app:latest not found
```

**Решение:**
- Использовать immutable теги: версию (`:v1.2.3`) или SHA256 digest (`my-app@sha256:abc...`).
- Убедиться, что образ с данным тегом существует в registry.

### Сценарий 6: Анализ логов kubelet и рантайма

Если `kubectl describe` не дает детальной информации, проверьте логи системных служб на узле:

```bash
# Проверка логов kubelet
journalctl -u kubelet | grep -iE "image pull|ErrImagePull|ImagePullBackOff"

# Проверка логов containerd (если используется)
journalctl -u containerd | grep -i "pull"
```

---

## Дополнительная информация

### Связанные темы

- [Определения и базовые концепции](./definitions.md) — терминология и жизненный цикл загрузки.
- [Распространённые ошибки](./common_errors.md) — причины и способы решения типовых проблем.
- [Лучшие практики](./best_practices.md) — мониторинг и предотвращение ошибок.
- [Air-gapped кластеры](./airgapped.md) — специфика работы в изолированных средах.
- [Сетевые проблемы](./network_issues.md) — настройка Proxy, TLS и NetworkPolicy.
