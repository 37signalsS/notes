# Контейнеризация и хранение образов в GitOps

## Роль контейнерных образов в GitOps
В GitOps цикл доставки разделяется на два артефакта: исходный код приложения и образ контейнера. Репозиторий инфраструктуры фиксирует желаемое состояние кластера, но не хранит сами образы — вместо этого в манифестах Kubernetes указываются ссылки на образы из реестра. Ключевое требование — детерминируемость: манифест должен ссылаться на неизменяемый артефакт.

Варианты ссылок:
*   Теги: удобны для людей, но могут быть мутируемыми.
*   Дайджесты (sha256): криптографически однозначные ссылки на конкретный слойный слепок образа.

Таблица:
| Способ | Плюсы | Минусы | Где уместно |
| --- | --- | --- | --- |
| image:repo/app:1.4.2 | Читаемо, просто | Риск перезаписи тега | Dev, автообновление |
| image:repo/app@sha256:... | Идемпотентно, точно | Менее читаемо | Staging/Prod, аудит |

## Практики контейнеризации для GitOps
*   Репродуцируемые сборки: фиксируйте версии базовых образов и инструментов.
*   Мультистейдж: минимизируйте итоговый слой, исключайте dev-зависимости.
*   Метаданные: добавляйте OCI-лейблы (version, vcs-url, revision).
*   Безопасность: не используйте root, ограничивайте capabilities, обновляйте базу пакетов.
*   Подписи и SBOM: подписывайте образы и публикуйте SBOM для трассируемости цепочки поставки.

Пример Dockerfile с мультистейдж-сборкой и непривилегированным исполнением:
```bash
FROM golang:1.22-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-s -w -X main.version=${VERSION}" -o /bin/app ./cmd/app

FROM gcr.io/distroless/static:nonroot
LABEL org.opencontainers.image.source="https://example.com/repo" 
      org.opencontainers.image.version="${VERSION}"
USER nonroot:nonroot
COPY --from=build /bin/app /app
ENTRYPOINT ["/app"]
```
## Хранение образов и политики реестров
Реестр — единственный источник бинарных артефактов. Для GitOps критичны:
*   Иммутабельность тегов и запрет перезаписи.
*   Политики ретенции и garbage collection.
*   Частные репозитории и протокол OCI с поддержкой подписей.
*   Репликация между регионами и кэширование (pull-through).
*   Хранение Helm-чартов как OCI-артефактов для консистентности.

Примеры: Docker Hub, Harbor, ECR, GCR/Artifact Registry, ACR — выбираются по требованиям к контролю доступа, репликации и доказуемости происхождения.

## Связь образов с манифестами Kubernetes
Рекомендуется закреплять образ по дайджесту, особенно для продуктивных окружений:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app
spec:
  template:
    spec:
      containers:
      - name: app
        image: registry.example.com/team/app@sha256:ab12cd...
        imagePullPolicy: IfNotPresent
```
Kustomize позволяет централизованно изменять образ:
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
images:
  - name: registry.example.com/team/app
    newName: registry.example.com/team/app
    newTag: 1.4.2
```
## Автоматизация обновления образов
Argo CD использует синхронизацию по Git. Обновление образов реализуется через генерацию коммитов в репозиторий манифестов. Два распространённых подхода:
*   Argo CD Image Updater: мониторит реестр и создаёт коммиты/PR с обновлёнными тегами или дайджестами.
```yaml
metadata:
  annotations:
    argocd-image-updater.argoproj.io/image-list: app=registry.example.com/team/app
    argocd-image-updater.argoproj.io/app.update-strategy: semver
    argocd-image-updater.argoproj.io/app.allow-tags: regexp:^1\.\d+\.\d+$
```
*   Flux Image Automation: контроллеры CRD для наблюдения за тегами и обновления манифестов.
```yaml
apiVersion: image.toolkit.fluxcd.io/v1beta2
kind: ImageRepository
metadata:
  name: app-repo
spec:
  image: registry.example.com/team/app
---
apiVersion: image.toolkit.fluxcd.io/v1beta2
kind: ImagePolicy
metadata:
  name: app-policy
spec:
  imageRepositoryRef:
    name: app-repo
  policy:
    semver:
      range: 1.x
---
apiVersion: image.toolkit.fluxcd.io/v1beta2
kind: ImageUpdateAutomation
metadata:
  name: app-auto
spec:
  sourceRef:
    kind: GitRepository
    name: manifests
  update:
    strategy: Setters
```
## Безопасность и проверка в кластере
Для валидации подписей образов применяются политики при приёме манифестов. Пример проверки подписи образа:
```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: verify-image-signature
spec:
  rules:
    - name: require-signed
      match:
        resources:
          kinds: ["Pod"]
      verifyImages:
        - image: "registry.example.com/team/app:*"
          key: "cosign.pub"
```
