# Pod Image Pull Errors: Диагностика

## Определения

**Диагностика Image Pull Errors** — пошаговый процесс выявления и устранения причин, по которым `kubelet` не может загрузить образ контейнера из registry.

**Events** — журнал событий pod'а, содержащий историю попыток pull, ошибки и статусы от `kubelet`. Основной источник информации для диагностики.

---

## Основные концепции

### Стратегия диагностики

Диагностика движется от общего к частному:

```
1. kubectl describe pod → анализ Events (тип ошибки)
2. Проверка имени/тега образа → manifest существует?
3. Проверка imagePullSecrets → аутентификация корректна?
4. Проверка сети/DNS → registry доступен с узла?
5. Проверка registry → rate limit, TLS, firewall
```

### Ключевые поля в выводе kubectl describe

| Раздел | Что искать | Значение |
| :--- | :--- | :--- |
| `Events[].Reason` | `Failed`, `BackOff` | Причина ошибки |
| `Events[].Message` | Текст ошибки | Конкретная причина (`manifest not found`, `unauthorized`) |
| `Events[].Count` | Количество повторов | Частота ошибок |
| `ContainerStatuses[].State.Waiting.Reason` | `ImagePullBackOff`, `ErrImagePull` | Текущий статус ожидания |

---

## Практические сценарии

### Сценарий 1: Проверка статуса пода и анализ Events

```bash
kubectl describe pod <pod-name>
```

**Ищите в разделе `Events`:**

```
Type     Reason     Age                From               Message
----     ------     ----               ----               -------
Warning  Failed     2m (x4 over 3m)    kubelet            Failed to pull image "my-app:1.1": rpc error: code = Unknown desc = Error response from daemon: manifest for my-app:1.1 not found
Warning  Failed     2m (x4 over 3m)    kubelet            Error: ErrImagePull
Normal   BackOff    1m (x6 over 2m)    kubelet            Back-off pulling image "my-app:1.1"
Warning  Failed     1m (x6 over 2m)    kubelet            Error: ImagePullBackOff
```

**Интерпретация:**
- `Failed to pull image` — kubelet попытался скачать образ, но получил ошибку от daemon (containerd/docker)
- `ErrImagePull` — начальная ошибка pull
- `Back-off pulling image` — kubelet повторяет попытку с увеличенной задержкой
- `ImagePullBackOff` — pod перешёл в состояние ожидания с exponential backoff

### Сценарий 2: Проверка имени образа

```bash
# Извлечение имени образа из pod
kubectl get pod <pod-name> -o jsonpath='{.spec.containers[*].image}'

# Проверка наличия образа в registry
docker pull <image-name>

# Или через crane (не требует docker daemon)
crane pull <image-name> <local-file>
```

**Автоматизация — извлечение имени образа и проверка:**

```bash
IMAGE=$(kubectl get pod <pod-name> -o jsonpath='{.spec.containers[0].image}')
echo "Проверка образа: $IMAGE"
crane digest "$IMAGE" 2>&1 || echo "Образ недоступен"
```

### Сценарий 3: Проверка imagePullSecrets

```bash
# Проверка secrets в pod
kubectl get pod <pod-name> -o jsonpath='{.spec.imagePullSecrets}'

# Проверка существования secret
kubectl get secret <secret-name> -n <namespace>

# Проверка типа secret
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.type}'
# Ожидаемый результат: kubernetes.io/dockerconfigjson

# Декодирование содержимого secret (для проверки)
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d
```

**Проверка ServiceAccount:**

```bash
# Проверка привязок SA
kubectl get serviceaccount default -n <namespace> -o jsonpath='{.imagePullSecrets}'

# Если пусто — secret не привязан, pod не сможет аутентифицироваться
```

### Сценарий 4: Проверка сети и DNS

```bash
# Проверка доступности registry с узла
ssh <node-name> "curl -I https://registry.example.com"

# Проверка DNS-разрешения
ssh <node-name> "nslookup registry.example.com"

# Проверка firewall правил (проверка порта 443)
ssh <node-name> "curl -v telnet://registry.example.com:443"

# Проверка TLS-сертификатов
ssh <node-name> "curl -v https://registry.example.com/v2/"
```

**Проверка DNS изнутри pod:**

```bash
kubectl run dns-test --image=busybox:1.28 --rm -it --restart=Never -- nslookup registry.example.com
```

### Сценарий 5: Проверка логов kubelet

```bash
# На проблемном узле
journalctl -u kubelet | grep -i "image pull\|ErrImagePull\|ImagePullBackOff"

# Для containerd
journalctl -u containerd | grep -i "pull"
```

---

## Дополнительная информация

### Связанные темы

- Определения и базовые концепции: [Definitions](./definitions.md)
- Распространённые ошибки и решения: [Common Errors](./common_errors.md)
- Диагностика по таблице решений: [Best Practices](./best_practices.md#сценарий-3-диагностика-по-таблице-решений)
- Air-gapped кластеры: [Air-gapped](./airgapped.md)
- Сетевые проблемы: [Network Issues](./network_issues.md)
