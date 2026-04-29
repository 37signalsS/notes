# Интеграция GitLab с Harbor

Руководство по настройке GitLab для работы с внешним OCI-реестром Harbor в dev-окружении K3s. Описывает отключение встроенного GitLab Registry и централизованное управление учетными данными для CI/CD.

> **Контекст:** Часть серии по созданию dev-окружения в K3s. Harbor используется как единый реестр для Docker-образов и Helm-чартов. См. [Архитектура K3s](./k3s_architecture.md), [Harbor Overview](../../../Docker/Docker_registries/Harbor/overview.md).

---

## Определения

| Термин | Описание |
|--------|----------|
| **GitLab Registry** | Встроенный Docker-реестр в GitLab. Может конфликтовать с внешними реестрами при неправильной настройке |
| **Harbor** | Внешний OCI-реестр с расширенными возможностями: сканирование уязвимостей, репликация, управление доступом. См. [Harbor Overview](../../../Docker/Docker_registries/Harbor/overview.md) |
| **GitLab CI/CD Variables** | Переменные окружения, доступные в пайплайнах. Поддерживают типы `Var` (значение) и `File` (содержимое файла) |
| **Group-level Variables** | Переменные, определенные на уровне группы GitLab. Наследуются всеми проектами группы |

**Навигация:** [Harbor Overview](../../../Docker/Docker_registries/Harbor/overview.md) | [GitLab CI Basics](../../../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md) | [GitLab K8s Integration](../../../CI-CD/GitLab_CI/Advanced/gitlab_kubernetes_integration_guide.md)

---

## Основные концепции

### Почему внешний Harbor вместо GitLab Registry?

| Критерий | GitLab Registry | Harbor |
|----------|-----------------|--------|
| **Сканирование уязвимостей** | Зависит от интеграции | Встроенное (Trivy/Clair) |
| **Управление доступом** | На уровне проектов | Детальная RBAC, робот-аккаунты |
| **Репликация** | Ограниченная | Полная поддержка мульти-реестра |
| **Helm-чарты** | Поддержка | Нативная поддержка OCI |
| **Подпись образов** | — | Notary/Cosign |
| **Веб-интерфейс** | Минимальный | Расширенный UI для управления образами |

**Решение:** В данной архитектуре Harbor развернут как отдельный сервис в K3s, GitLab использует его как внешний реестр.

### Архитектура интеграции

```
┌─────────────────────────────────────────────────────────────┐
│                      GitLab (Helm Chart)                     │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐    ┌─────────────────────────────────┐  │
│  │  GitLab CI/CD   │    │   GitLab Registry (отключен)    │  │
│  │   Pipelines     │    │   global.registry.enabled: false│  │
│  │       │         │    └─────────────────────────────────┘  │
│  │       ↓         │                                         │
│  │  Push/Pull    │                                         │
│  └───────│─────────┘                                         │
└──────────┼────────────────────────────────────────────────────┘
           │ HTTPS (с CA-сертификатом)
           ↓
┌─────────────────────────────────────────────────────────────┐
│                    Harbor (в K3s)                            │
│  ┌─────────────────┐    ┌─────────────────────────────────┐  │
│  │  Docker Images  │    │      Helm Charts (OCI)          │  │
│  │  library/       │    │      charts/                    │  │
│  └─────────────────┘    └─────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Проблема: Конфликт реестров

При развертывании GitLab через Helm-чарт с внешним Harbor может возникнуть проблема: внутренние сервисы GitLab пытаются использовать встроенный реестр, даже если он отключен в основной конфигурации.

**Причина:** В Helm-чарте GitLab параметр `registry.enabled` должен быть явно указан в **двух местах**:

1. Глобальная секция `global.registry`
2. Корневая секция `registry`

**Симптомы:**

- Ошибки push/pull образов
- Конфликты доменных имен
- Невозможность аутентификации во внешнем реестре

---

## Практические сценарии

### 1. Отключение встроенного GitLab Registry

Для корректной работы с внешним Harbor явно укажите отключение реестра в обоих местах `values.yaml`:

```yaml
# gitlab-values.yaml

global:
  registry:
    enabled: false
    # Опционально: указать внешний реестр для GitLab
    # externalUrl: https://harbor.example.com

# Отключение компонента Registry в GitLab
registry:
  enabled: false
```

**Применение конфигурации:**

```bash
# Обновление GitLab с новыми значениями
helm upgrade gitlab gitlab/gitlab \
  --namespace gitlab \
  -f gitlab-values.yaml \
  --timeout 10m \
  --wait
```

**Проверка:**

```bash
# Убедитесь, что pod реестра не запущен
kubectl get pods -n gitlab -l app=registry

# Проверка логов GitLab на отсутствие ошибок реестра
kubectl logs -n gitlab -l app=gitlab-rails --tail=50
```

### 2. Настройка переменных CI/CD для Harbor

Для централизованного управления учетными данными создайте переменные на уровне группы GitLab.

#### Шаг 1: Создание группы

1. В GitLab перейдите в **Menu → Groups → Create group**
2. Назовите группу (например, `dev`)
3. Установите видимость **Private**

#### Шаг 2: Добавление переменных

Перейдите в **Group → Settings → CI/CD → Variables → Add variable**

| Ключ | Значение | Тип | Опции | Описание |
|------|----------|-----|-------|----------|
| `dev.registry` | `harbor.example.com` | `Var` | — | Адрес Harbor (без `https://`) |
| `dev.registry-user` | `admin` или `robot$ci` | `Var` | `Masked` | Пользователь для push/pull |
| `dev.registry-password` | `<токен или пароль>` | `Var` | `Masked`, `Protected` | Пароль или токен робот-аккаунта |
| `dev.se` | (содержимое `root-ca.crt`) | `File` | — | Корневой CA для доверия к Harbor |

> **Примечание:** Переменная типа `File` сохраняется во временный файл на Runner. Путь к файлу доступен через переменную окружения `dev.se`. Используйте в пайплайнах для настройки доверия к CA.

#### Шаг 3: Использование в пайплайне

Пример `.gitlab-ci.yml` с использованием переменных:

```yaml
build-and-push:
  stage: build
  image: $dev.registry/library/kube-utils:v1.28.6
  variables:
    IMAGE_NAME: $dev.registry/$CI_PROJECT_PATH_SLUG:$CI_COMMIT_SHA
  script:
    # Добавление CA в доверенные
    - cp $dev.se /usr/local/share/ca-certificates/custom-ca.crt
    - update-ca-certificates
    # Аутентификация в Harbor
    - docker login $dev.registry -u $dev.registry-user -p $dev.registry-password
    # Сборка и push образа
    - docker build -t $IMAGE_NAME .
    - docker push $IMAGE_NAME
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
```

### 3. Получение CA-сертификата для переменной `dev.se`

Источник сертификата зависит от способа установки Harbor:

**Вариант A: cert-manager в Kubernetes**

```bash
# Получение корневого CA из секрета cert-manager
kubectl get secret dfca-ca-key-pair -n cert-manager \
  -o jsonpath='{.data.ca\.crt}' | base64 -d > root-ca.crt
```

**Вариант B: Ручная установка Harbor**

```bash
# Копирование из директории сертификатов Harbor
cp /opt/harbor/certs/root-ca.crt ./root-ca.crt
```

**Содержимое `root-ca.crt`** скопируйте в переменную `dev.se` (тип `File`).

---

## Дополнительная информация

### Связанные темы

- **Установка:** [Установка GitLab через Helm](../gitlab_kubernetes_helm_installation.md), [Установка в закрытом контуре](../gitlab_offline_kubernetes_installation.md)
- **Harbor:** [Обзор Harbor](../../../Docker/Docker_registries/Harbor/overview.md), [Установка Harbor](../../../Docker/Docker_registries/Harbor/installation.md), [Сертификаты](../../../Docker/Docker_registries/Harbor/certificates.md)
- **GitLab CI:** [Основы GitLab CI](../../../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md), [Kubernetes Integration](../../../CI-CD/GitLab_CI/Advanced/gitlab_kubernetes_integration_guide.md)
- **Dev-окружение:** [Архитектура K3s](./k3s_architecture.md), [Kubeutils Image](./kubeutils_image.md), [Dev Container Helm](./dev_container_helm_deployment.md)

### Предупреждения

| Аспект | Риск | Рекомендация |
|--------|------|--------------|
| **Пароли в переменных** | Утечка через логи | Используйте `Masked` и робот-аккаунты с ограниченным сроком |
| **CA-сертификат** | Истечение срока | Мониторьте срок действия, обновляйте за 30 дней до истечения |
| **Доступ к Harbor** | Несанкционированный push | Создавайте робот-аккаунты с минимальными правами |
| **HTTP vs HTTPS** | Перехват трафика | Всегда используйте HTTPS для Harbor |

### Альтернативные подходы

| Подход | Описание | Когда использовать |
|--------|----------|-------------------|
| **GitLab Registry** | Встроенный реестр GitLab | Простые сценарии, один реестр |
| **Harbor** | Внешний реестр с расширенными функциями | Корпоративная среда, несколько реестров |
| **GHCR** | GitHub Container Registry | Проекты на GitHub |
| **Cloud Registry** | ECR, GCR, ACR | Облачные нативные решения |
