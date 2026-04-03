# Pod Image Pull Errors: Air-gapped кластеры

## Определения

**Air-gapped кластер (Offline)** — кластер Kubernetes, развёртываемый в изолированной среде без доступа к интернету. Все образы контейнеров должны быть предварительно загружены в локальный реестр внутри закрытого контура.

**Закрытый контур** — изолированная сеть без прямого доступа к внешним registry (Docker Hub, GCR, ECR). Требует использования локальных реестров (Harbor, Docker Registry) и зеркал пакетов.

**Локальный registry** — внутренний реестр контейнерных образов, доступный внутри закрытого контура (например, `local-registry:5000`).

---

## Основные концепции

### Специфика Image Pull Errors в air-gapped средах

В air-gapped кластерах стандартные image pull errors (`ErrImagePull`, `ImagePullBackOff`) возникают по следующим причинам:

| Причина | Симптом | Решение |
| :--- | :--- | :--- |
| Образ отсутствует в локальном registry | `manifest not found` | Загрузить образ через `docker save/load` |
| Некорректный URL локального registry | `dial tcp: lookup failed` | Проверить DNS и доступность registry |
| `imagePullPolicy: Always` для локального образа | Излишние попытки pull | Использовать `IfNotPresent` или `Never` |
| Отсутствует TLS-сертификат registry | `x509: certificate signed by unknown authority` | Настроить доверие к CA registry |

### Принцип работы с образами

```
Машина с интернетом          Закрытый контур
┌─────────────────┐         ┌──────────────────────────┐
│ docker pull     │         │  docker load             │
│ docker save     │  ────►  │  docker tag              │
│ Сохранение .tar │  SCP    │  docker push → Registry  │
└─────────────────┘         └──────────────────────────┘
                                      │
                                      ▼
                              Kubernetes Pod
                              (image: local-registry:5000/...)
```

### imagePullPolicy для air-gapped

| Политика | Применение |
| :--- | :--- |
| `IfNotPresent` | **Рекомендуется** — использует локальный кэш узла |
| `Never` | Допустимо — только локальные образы, без pull |
| `Always` | **Не рекомендуется** — попытка pull вызовет ошибку |

---

## Практические сценарии

### Сценарий: Перенос образа в air-gapped кластер

#### Шаг 1: Скачать образы на машине с доступом в интернет

```bash
docker pull my-app:1.0
docker save -o my-app.tar my-app:1.0
```

#### Шаг 2: Передать архив в offline-кластер

```bash
scp my-app.tar admin@offline-node:/tmp/
```

#### Шаг 3: Загрузить в локальный registry

```bash
# На узле закрытого контура
docker load -i /tmp/my-app.tar
docker tag my-app:1.0 local-registry:5000/my-app:1.0
docker push local-registry:5000/my-app:1.0
```

#### Шаг 4: Использование в манифесте

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-app
spec:
  containers:
  - name: app
    image: local-registry:5000/my-app:1.0
    imagePullPolicy: IfNotPresent
```

### Диагностика проблем

```bash
# Проверить доступность registry с узла
curl -k https://local-registry:5000/v2/_catalog

# Проверить наличие образа в registry
crane digest local-registry:5000/my-app:1.0

# Проверить события pod
kubectl describe pod my-app | grep -A5 Events
```

---

## Дополнительная информация

### Связанные темы

- Полное руководство по offline-развёртыванию: [Kubespray: Offline установка](../../../Installation/Kubespray/offline_installation/offline_definitions.md)
- Определения image pull errors: [Pod Image Pull Errors: Определения](./definitions.md)
- Настройка локального registry: [Harbor overview](../../../../Docker/Docker_registries/Harbor/overview.md)
- Безопасность образов: [Common Errors](./common_errors.md)
