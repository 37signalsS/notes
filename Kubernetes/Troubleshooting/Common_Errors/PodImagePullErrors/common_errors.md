# Ошибки загрузки образов (Image Pull Errors): Распространённые ошибки

## Определения

В данном разделе рассматриваются конкретные коды ошибок и технические ситуации, приводящие к состояниям `ErrImagePull` и `ImagePullBackOff`. Базовые термины и жизненный цикл процесса описаны в разделе [Определения](./definitions.md).

---

## Основные концепции

### Классификация типовых ошибок и статус-коды

Ошибки загрузки транслируются от реестра через Container Runtime Interface (CRI) в события Kubernetes. Понимание gRPC статус-кодов помогает при анализе логов `containerd` или `CRI-O`.

| Код / Сообщение | gRPC Code | Категория | Корневая причина |
| :--- | :--- | :--- | :--- |
| `manifest not found` | `NotFound` (5) | Образ / Тег | Опечатка в имени, отсутствие тега или архитектуры. |
| `unauthorized` (401) | `Unauthenticated` (16) | Аутентификация | Отсутствует `imagePullSecrets`, неверные креды. |
| `forbidden` (403) | `PermissionDenied` (7) | Авторизация | Нет прав на Pull (даже если логин верен). |
| `too many requests` (429) | `Unavailable` (14) | Лимиты | Превышена квота (Rate Limit) реестра (Docker Hub). |
| `connection refused` | `Internal` (13) | Сеть | Реестр недоступен, неверный порт, блокировка Firewall. |
| `deadline exceeded` | `DeadlineExceeded` (4) | Доступность | Таймаут сети, проблемы с MTU или прокси. |
| `failed to extract layer` | `Internal` (13) | Хранилище | Повреждение слоев, ошибки Snapshotter (OverlayFS). |

---

## Практические сценарии

### Сценарий 1: Неверное имя или тег образа (Manifest Not Found)

**Симптом:**
В `kubectl describe pod` отображается ошибка `manifest for <image>:<tag> not found`.

**Причина:**
Указанный тег не существует в реестре. Часто случается при использовании динамических версий (хеш коммита), которые еще не были запушены CI/CD.

**Решение:**
1.  Проверьте наличие образа через `skopeo inspect docker://registry.io/app:tag`.
2.  Убедитесь, что в имени образа нет лишних символов (пробелов, кавычек) и соблюден регистр (Case Sensitivity).

### Сценарий 2: Ошибки аутентификации в приватных реестрах (401 Unauthorized)

**Симптом:**
Ошибка `unauthorized: authentication required` или `pull access denied`.

**Причина:**
`kubelet` не смог найти или использовать валидные учетные данные.

**Решение:**
1.  Создайте секрет в нужном Namespace: `kubectl create secret docker-registry regcred ...`.
2.  **Глобальное решение:** Привяжите секрет к `ServiceAccount`, чтобы он автоматически добавлялся во все поды:
    ```bash
    kubectl patch serviceaccount default -p '{"imagePullSecrets": [{"name": "regcred"}]}'
    ```

### Сценарий 3: Превышение лимитов Docker Hub (429 Too Many Requests)

**Симптом:**
Ошибка `toomanyrequests: You have reached your pull rate limit`.

**Решение:**
1.  **Auth:** Используйте `imagePullSecret` даже для бесплатных аккаунтов (лимиты повышаются со 100 до 200).
2.  **Mirroring:** Настройте локальное зеркало (Pull-through Cache) в Harbor.
3.  **Public Clouds:** Используйте зеркала облачных провайдеров (например, `mirror.gcr.io` или `public.ecr.aws`).

### Сценарий 4: Несоответствие архитектуры (Architecture Mismatch)

**Симптом:**
Образ скачивается, но контейнер не запускается с ошибкой `exec format error` или в логах CRI видна ошибка `no matching manifest for linux/amd64 in the manifest list`.

**Причина:**
Попытка запустить образ, собранный под `arm64`, на узле с архитектурой `amd64` (или наоборот).

**Решение:**
1.  Проверьте поддерживаемые архитектуры образа: `skopeo inspect --raw docker://registry.io/app:tag | jq .manifests`.
2.  Используйте Multi-arch сборки (Docker Buildx / Buildah) для поддержки обоих типов узлов.

### Сценарий 5: Истечение токенов в облачных реестрах (ECR / Artifact Registry)

**Симптом:**
Поды успешно запускались в течение первых 12 часов, но затем начали падать с `ImagePullBackOff`.

**Причина:**
Токены аутентификации AWS ECR или Google Artifact Registry временные (обычно 12ч). Если вы создали статический `Secret` вручную, он протухнет.

**Решение:**
1.  **IAM Roles:** Используйте механизмы интеграции провайдера (IRSA в AWS, Workload Identity в GCP). В этом случае `kubelet` сам получает токен.
2.  **Helper:** Используйте автоматические обновители секретов (например, `aws-ecr-credential-helper` или CronJob для `kubectl create secret`).

### Сценарий 6: Ошибки Snapshotter и Snapshot Layer Corruption

**Симптом:**
Ошибка `failed to get shared layer` или `failed to extract layer`.

**Причина:**
Повреждение локального кэша образов на узле из-за сбоев диска, жесткой перезагрузки узла или багов в драйвере OverlayFS.

**Решение:**
1.  Очистите кэш образов на проблемном узле: `crictl rmi --prune`.
2.  Если проблема сохраняется, удалите содержимое `/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs` и перезапустите рантайм.

### Сценарий 7: Проблемы с TLS и сертификатами (x509)

**Симптом:**
`x509: certificate signed by unknown authority`.

**Решение:**
1.  Добавьте CA сертификат в `/usr/local/share/ca-certificates/` на всех узлах и выполните `update-ca-certificates`.
2.  Для `containerd` используйте `hosts.toml` для настройки `ca = "/path/to/ca.crt"` без изменения системного хранилища.

### Сценарий 8: Использование неизменяемых (Immutable) образов

**Проблема:**
Использование тега `:latest` или изменяемых версий (например, `:stable`) может привести к тому, что разные узлы кластера будут запускать разные версии одного и того же образа из-за кэширования.

**Рекомендация:**
Используйте SHA256 digest для гарантированной идентичности:
```yaml
image: myregistry.io/my-app@sha256:45b23dee...
```
Это полностью исключает ошибки `manifest not found` для уже запущенных систем и повышает безопасность.

### Сценарий 9: Проблемы с DNS-именем реестра

**Симптом:**
Ошибка `dial tcp: lookup registry.example.com: no such host` или `i/o timeout` при попытке загрузить образ.

**Причина:**
Рантайм контейнеров не может разрешить DNS-имя реестра образов.

**Диагностика:**

1.  **Проверка DNS из тестового пода:**
    ```bash
    kubectl run dns-debug --image=busybox --rm -it -- nslookup registry.example.com
    ```

2.  **Проверка CoreDNS:**
    ```bash
    kubectl get pods -n kube-system -l k8s-app=kube-dns
    kubectl logs -n kube-system -l k8s-app=kube-dns
    ```

3.  **Проверка NodeLocal DNSCache:**
    ```bash
    kubectl get daemonset -n kube-system node-local-dns
    kubectl logs -n kube-system -l k8s-app=node-local-dns
    ```

**Возможные причины и решения:**

| Причина | Диагностика | Решение |
| :--- | :--- | :--- |
| CoreDNS не работает | `kubectl get pods -n kube-system` — поды в `CrashLoopBackOff` | Перезапуск CoreDNS, проверка конфигурации |
| NetworkPolicy блокирует DNS | Проверка политик в неймспейсе | Добавить разрешение на UDP/TCP порт 53 |
| NodeLocal DNSCache не работает на узлах | Логи `node-local-dns` содержат ошибки | Перезапустить DaemonSet, проверить конфигурацию |
| Внешний DNS не резолвится | `nslookup` из тестового пода не работает | Проверить upstream DNS в CoreDNS Corefile |
| Проблема с `/etc/resolv.conf` пода | Проверка конфигурации пода | Настроить `dnsConfig` или `dnsPolicy` |

**Специфика NodeLocal DNSCache:**
Если `node-local-dns` работает на части узлов, а на других — нет, это приводит к неконсистентному поведению: поды на одних узлах могут загружать образы, а на других — нет.

**Алгоритм диагностики при проблемах с NodeLocal DNSCache:**
1.  Проверить статус DaemonSet: `kubectl get ds -n kube-system node-local-dns`.
2.  Проверить логи подов: `kubectl logs -n kube-system -l k8s-app=node-local-dns`.
3.  Если поды в `CrashLoopBackOff`, проверить:
    - Доступность CoreDNS Service IP (обычно `10.96.0.10`).
    - Корректность ConfigMap с конфигурацией.
    - Наличие необходимых ресурсов (CPU/Memory).
4.  Временное решение: удалить проблемные поды DaemonSet для перезапуска.
5.  Для полного восстановления: `kubectl rollout restart daemonset node-local-dns -n kube-system`.

**Важно:** NodeLocal DNSCache использует IP `169.254.20.10` (по умолчанию) для локального кэширования. Убедитесь, что этот IP не конфликтует с другими сервисами в кластере.

---

## Дополнительная информация

### Связанные темы

- [Определения и базовые концепции](./definitions.md) — терминология и жизненный цикл загрузки.
- [Пошаговая диагностика](./diagnostics.md) — алгоритм поиска неисправностей (L1-L5).
- [Лучшие практики](./best_practices.md) — предотвращение ошибок в продакшене.
- [Сетевые проблемы](./network_issues.md) — диагностика DNS, Proxy и MTU.
- [Air-gapped кластеры](./airgapped.md) — настройка `hosts.toml` и работа в изоляции.
