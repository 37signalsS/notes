# Ошибки загрузки образов (Image Pull Errors): Air-gapped кластеры

## Определения

**Air-gapped кластер (Offline)** — инфраструктура Kubernetes, развернутая в полностью изолированной сетевой среде без прямого или косвенного доступа к публичным сетям и внешним реестрам образов. Общие стратегии синхронизации описаны в разделе **[Изолированные среды (Air-gapped)](../../../CI-CD/Core_Concepts/air_gapped_environments.md)**.

**Закрытый контур** — периметр безопасности, ограничивающий сетевые взаимодействия только внутренними доверенными ресурсами. Требует наличия локальных сервисов для всех внешних зависимостей (образы, пакеты ОС, Helm-чарты).

**Локальный реестр (Internal Registry)** — служба хранения образов внутри контура (например, Harbor, Nexus, Docker Distribution). Является единственным легитимным источником образов для узлов кластера.

**Зеркалирование образов (Image Mirroring)** — процесс синхронизации образов между внешним и внутренним реестрами с сохранением структуры слоев и метаданных.

**Перехват реестра (Registry Redirection)** — конфигурация рантайма контейнеров (containerd, CRI-O), позволяющая прозрачно перенаправлять запросы с публичных адресов (например, `docker.io`) на локальные зеркала без изменения манифестов подов.

**Sandbox Image (Pause container)** — вспомогательный образ (обычно `registry.k8s.io/pause`), используемый Kubernetes для создания сетевого пространства имен пода. В air-gapped средах это критическая точка отказа, если рантайм пытается скачать его извне.

---

## Основные концепции

### Специфика ошибок Image Pull в изолированных средах

В air-gapped кластерах ошибки загрузки практически всегда связаны с конфигурацией инфраструктуры или отсутствием данных, а не с временными сетевыми сбоями.

| Корневая причина | Сообщение об ошибке | Особенности в Air-gapped |
| :--- | :--- | :--- |
| **Отсутствие образа** | `manifest not found` / `404 Not Found` | Образ не был синхронизирован или загружен в локальный реестр. |
| **Проблемы DNS** | `no such host` / `lookup failed` | Узлы кластера не могут разрешить имя локального реестра. |
| **TLS/SSL ошибки** | `x509: certificate signed by unknown authority` | Отсутствие корневого CA локального реестра в доверенном хранилище узла. |
| **Ошибка маршрутизации** | `connection timed out` | Сетевые политики (NetworkPolicies) или firewall блокируют доступ к реестру. |
| **Sandbox Failure** | `failed to pull sandbox image` | Рантайм не может запустить под из-за отсутствия локального образа `pause`. |

### Проблема Sandbox Image (Pause container)

Для работы любого пода Kubelet требует наличия образа "паузы". По умолчанию рантайм пытается скачать его с `registry.k8s.io/pause`.
В изолированной среде необходимо:
1. Заранее загрузить образ `pause` в локальный реестр.
2. Явно переопределить путь к нему в конфигурации рантайма (`containerd` или `CRI-O`) или через аргументы запуска `kubelet` (`--pod-infra-container-image`).

### Конфигурация рантайма: containerd

Для современных версий containerd (1.5+) рекомендуется использовать систему `hosts.toml`, которая позволяет настраивать зеркала и параметры TLS без перезагрузки демона.

**1. Включение поддержки в `/etc/containerd/config.toml`:**
```toml
[plugins."io.containerd.grpc.v1.cri".registry]
  config_path = "/etc/containerd/certs.d"
```

**2. Настройка зеркала для `docker.io` в `/etc/containerd/certs.d/docker.io/hosts.toml`:**
```toml
server = "https://registry-1.docker.io"

[host."https://harbor.local/v2/proxy-docker-io"]
  capabilities = ["pull", "resolve"]
```

**3. Переопределение Sandbox Image:**
В `/etc/containerd/config.toml`:
```toml
[plugins."io.containerd.grpc.v1.cri"]
  sandbox_image = "harbor.local/k8s/pause:3.9"
```

### Конфигурация рантайма: CRI-O

CRI-O использует файл `/etc/containers/registries.conf` (или файлы в `/etc/containers/registries.conf.d/`) для управления зеркалами.

Пример настройки в формате TOML:
```toml
[[registry]]
location = "docker.io"

[[registry.mirror]]
location = "harbor.local/v2/proxy-docker-io"

[unqualified-search-registries]
registries = ['harbor.local', 'docker.io']
```

Переопределение образа паузы в `/etc/crio/crio.conf`:
```toml
[crio.image]
pause_image = "harbor.local/k8s/pause:3.9"
```

---

## Практические сценарии

### Сценарий 1: Синхронизация образов через Skopeo

`skopeo` — основной инструмент для air-gapped сред. Он позволяет работать с образами без локального Docker-демона.

**1. Копирование одного образа (с поддержкой всех архитектур):**
```bash
# --all копирует все платформы (amd64, arm64 и т.д.), что критично для мультиплатформенных кластеров
skopeo copy --all docker://docker.io/library/nginx:1.25 dir:/tmp/nginx-image
```

**2. Массовая синхронизация (skopeo sync):**
Позволяет синхронизировать целые репозитории или списки образов.
```bash
# Файл images.yaml
# docker.io/library:
#   images:
#     nginx: [ "1.25", "latest" ]
#     redis: [ "7.0" ]

skopeo sync --all --src yaml --dest docker images.yaml harbor.local/library
```

### Сценарий 2: Добавление сертификата и аутентификация

Если локальный реестр защищен паролем и использует самоподписанный TLS, настройки выполняются в `hosts.toml` (для containerd).

**Конфигурация `/etc/containerd/certs.d/harbor.local/hosts.toml`:**
```toml
server = "https://harbor.local"

[host."https://harbor.local"]
  capabilities = ["pull", "resolve"]
  # Путь к CA сертификату для этого конкретного хоста
  ca = "/etc/containerd/certs.d/harbor.local/ca.crt"
  
  [host."https://harbor.local".header]
    # base64(username:password)
    authorization = "Basic dXNlcm5hbWU6cGFzc3dvcmQ="
```

### Сценарий 3: Использование ImagePolicyWebhook

В крупных организациях для автоматической подмены путей к образам (например, с `docker.io/nginx` на `internal-registry.io/nginx`) используется **ImagePolicyWebhook** или мутирующие Admission-контроллеры (Kyverno, Gatekeeper). Это позволяет разработчикам использовать стандартные манифесты, которые автоматически корректируются под инфраструктуру air-gapped.

### Сценарий 4: Диагностика и проверка через crictl

`crictl` — CLI для взаимодействия с CRI-совместимыми рантаймами. Он позволяет проверить настройки "глазами" Kubernetes, минуя Docker.

**1. Проверка настроек рантайма:**
```bash
# Проверка используемого sandbox_image
crictl info | grep -A 5 "sandboxImage"
```

**2. Ручная проверка загрузки образа:**
```bash
# Тестовый пулл образа через рантайм
# Если зеркала настроены верно, запрос к docker.io уйдет на локальный реестр
crictl pull docker.io/library/nginx:1.25
```

**3. Просмотр логов рантайма:**
Если пулл не удается, причины (DNS, TLS, Auth) будут видны в системном логе:
```bash
journalctl -u containerd -f
# или
journalctl -u crio -f
```

---

## Дополнительная информация

### Связанные темы

- [Kubespray: Offline установка](../../../Installation/Kubespray/offline_installation/offline_definitions.md) — базовые понятия и подготовка артефактов для оффлайн-кластера.
- [Kubespray: Диагностика оффлайн-установки](../../../Installation/Kubespray/offline_installation/troubleshooting.md) — решение проблем с Cilium digest и доверием к сертификатам.
- [Определения и терминология](./definitions.md) — базовые статусы `ErrImagePull` и `ImagePullBackOff`.
- [Harbor: Обзор](../../../../Docker/Docker_registries/Harbor/overview.md) — настройка и эксплуатация корпоративного реестра образов.
- [Longhorn: Установка в закрытом контуре](../../../Storage/longhorn-air-gapped.md) — практический пример массового переноса образов и деплоя в изоляции.
- [Пошаговая диагностика](./diagnostics.md) — общий алгоритм поиска причин ошибок загрузки.
- [Сетевые проблемы](./network_issues.md) — отладка DNS и прокси в Kubernetes.
- [Среды выполнения контейнеров](../../../Concepts/container_runtime.md) — архитектура CRI, containerd и CRI-O.
