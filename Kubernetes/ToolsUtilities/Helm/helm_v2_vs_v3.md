# Сравнение версий Helm (v2, v3, v4)

История развития Helm отражает эволюцию Kubernetes: от клиент-серверной архитектуры с избыточными правами (v2) к безопасной клиентской модели (v3) и современному подходу на базе Server-Side Apply и WebAssembly (v4).

> **Статус поддержки (состояние на 2026 г.):**
> *   **Helm v2:** EOL (End of Life) с 13 ноября 2020 года. Использование запрещено.
> *   **Helm v3:** Bug fixes до июля 2026, Security fixes до ноября 2026 (EOL). Требуется миграция.
> *   **Helm v4:** Актуальная стабильная версия (релиз в ноябре 2025).

---

## Определения

| Термин | Описание |
|--------|----------|
| **Tiller** | Серверный компонент Helm 2, работавший в кластере с правами `cluster-admin`. Полностью удален в v3. |
| **Three-way merge** | (v3) Сравнение желаемого состояния (чарт), последней ревизии Helm и текущего живого состояния кластера. |
| **Server-Side Apply (SSA)** | (v4) Механизм Kubernetes, при котором логика слияния манифестов и управление полями (field ownership) выполняется на стороне API-сервера. |
| **WASM Plugin Runtime** | (v4) Изолированная среда выполнения плагинов (Extism), обеспечивающая безопасность и кроссплатформенность расширений. |
| **apiVersion** | Версия формата чарта: `v1` (v2 legacy), `v2` (v3/v4 основной), `v3` (v4 экспериментальный/OCI-native). |
| **Release Storage** | Хранилище состояний релизов: ConfigMaps в `kube-system` (v2), Secrets в namespace релиза (v3/v4). |
| **Hook** | Аннотированный ресурс (Job, Pod), который запускается в определённой точке жизненного цикла релиза (install, upgrade, delete). |
| **Drift** | Расхождение между текущим состоянием ресурса в кластере и тем, что определено в чарте. В v4 отслеживается через `managedFields`. |
| **Field Ownership** | Механизм SSA, при котором API-сервер отслеживает, какой менеджер управляет каждым полем манифеста. |
| **Immutability (дигест)** | Установка чарта по SHA-дигесту (`@sha256:...`) вместо тега, гарантирующая неизменность артефакта. |

---

## Базовые концепции

### Архитектурная эволюция

| Аспект | Helm v2 | Helm v3 | Helm v4 |
| :--- | :--- | :--- | :--- |
| **Модель управления** | Client-Server (Tiller) | Client-only | Client-only (SDK v4) |
| **Стратегия деплоя** | Two-way merge | Three-way merge | **Server-Side Apply (SSA)** |
| **Безопасность** | RBAC для Tiller | RBAC пользователя | RBAC пользователя + WASM Sandbox |
| **Хранение релизов** | ConfigMaps в `kube-system` | Secrets в namespace релиза | Secrets (SSA-aware) |
| **Уникальность имён** | Глобальная (на кластер) | В пределах namespace | В пределах namespace |
| **Плагины** | Локальные бинарные файлы | Локальные бинарные файлы | **OCI-артефакты (WASM)** |

### Хранение релизов и его последствия

**Helm v2 (ConfigMaps в kube-system):**
Все релизы хранились в ConfigMaps в namespace `kube-system` с глобально уникальными именами. Это означало, что нельзя было иметь два релиза с одним именем в разных namespace. Удаление namespace приводило к потере истории релизов, но сами ConfigMaps оставались в `kube-system`.

**Helm v3 (Secrets в namespace релиза):**
Переход на Secrets в namespace самого релиза. Это решает проблему глобальной уникальности: теперь можно разворачивать одноименные чарты в разных namespace. Secrets содержат снапшоты манифестов и истории ревизий.

**Helm v4 (SSA-aware Secrets):**
Secrets продолжают использоваться, но информация о владельцах полей (field ownership) синхронизируется с `managedFields` в Kubernetes. Это позволяет Helm v4 безопасно сосуществовать с другими контроллерами.

### Поведение хуков и жизненный цикл

В Helm v2 хуки были менее предсказуемы при откатах. В Helm v3/v4 введены детерминированные политики удаления хуков:

- **`hook-succeeded`**: Удаляет хук только после успешного выполнения.
- **`hook-failed`**: Удаляет хук только после неудачи (для повтора).
- **`before-hook-creation`**: Удаляет предыдущий хук перед созданием нового (гарантирует отсутствие дублей).

**Важно для SRE:** В Helm v4 хуки по умолчанию не являются частью SSA-владельцев. Если хук (Job) изменён внешним контроллером, Helm v4 не будет конфликтовать при обновлении чарта.

### Безопасность и RBAC

**Helm 2 (Проблема Tiller):**
Tiller часто устанавливался с правами `cluster-admin`, что позволяло любому пользователю с доступом к Tiller манипулировать любыми ресурсами в кластере, обходя персональные ограничения RBAC. Это создавало серьезный вектор атаки (Privilege Escalation).

**Helm 3 (Интеграция с RBAC):**
Полный отказ от Tiller. Все операции выполняются напрямую через Kubernetes API, используя права текущего пользователя из `kubeconfig`. Это сделало Helm нативно совместимым с многопользовательскими кластерами. Архитектура упростилась: клиент Helm напрямую взаимодействует с API-сервером, что устраняет центральную точку отказа.

**Helm v4 (Изоляция плагинов и SSA):**
Внедрение WASM ограничивает доступ расширений к хост-системе (Sandboxed execution). Использование SSA позволяет Kubernetes защищать поля, управляемые другими контроллерами (например, мутации Sidecar-инжекторов), предотвращая их случайное затирание клиентом Helm.

---

### Совет по собеседованию

**Вопрос:** Опытный коллега упоминает, что Helm 3 гораздо безопаснее, чем Helm 2. О каких серьезных архитектурных изменениях идет речь и почему они важны?

**Ответ:** Речь идет об **удалении Tiller** — серверного компонента Helm 2. В Helm 2 клиент отправлял команды Tiller-у, который работал внутри кластера часто с правами `cluster-admin`. Это создавало огромную дыру в безопасности: любой пользователь с доступом к Tiller мог управлять всем кластером. Helm 3 полностью исключил Tiller. Теперь клиент взаимодействует с API-сервером напрямую, используя собственные учетные данные пользователя и разрешения, определенные через **Kubernetes RBAC**. Это упрощает архитектуру, повышает безопасность и делает управление развертыванием стандартным процессом, полностью подконтрольным политикам доступа кластера. В Helm 4 эта безопасность усилена песочницей для плагинов (WASM).

---

## Стратегии слияния манифестов

1.  **Two-way merge (v2):** Сравнивались только чарт и предыдущая ревизия Helm. Если ресурс был изменен вручную через `kubectl edit`, Helm v2 не видел этого изменения и мог некорректно применить апдейт (или просто проигнорировать дрейф).
2.  **Three-way merge (v3):** Сравниваются три источника: новый чарт + сохранённая ревизия Helm + живое состояние в кластере. Это позволяет Helm 3 сохранять изменения, внесенные внешними контроллерами или администраторами, если они не конфликтуют с чартом.
3.  **Server-Side Apply (v4):** Логика слияния делегируется API-серверу Kubernetes.
    *   **Владение полями (Field Ownership):** Kubernetes отслеживает секцию `managedFields`. Если Helm управляет полем `image`, а HPA управляет полем `replicas`, они больше не конфликтуют при обновлении.
    *   **Разрешение конфликтов:** Если два инструмента пытаются управлять одним полем одновременно, API-сервер выдаёт ошибку, требуя явного "захвата" (force-apply).

---

## Практические сценарии

### Сравнение формата чартов (Chart API)

| Функция | apiVersion: v1 (v2) | apiVersion: v2 (v3/v4) |
| :--- | :--- | :--- |
| **Файл зависимостей** | `requirements.yaml` | Секция `dependencies` в `Chart.yaml` |
| **Типы чартов** | Только `application` | `application` и `library` |
| **Lock-файл** | Отсутствует | `Chart.lock` |
| **Директория CRD** | Обрабатывается как шаблоны | Директория `crds/` (приоритетная установка) |

#### Пример миграции зависимостей (v1 → v2)

**Helm 2 (`requirements.yaml`):**
```yaml
dependencies:
- name: redis
  version: "10.5.x"
  repository: "https://charts.bitnami.com/bitnami"
```

**Helm 3/4 (`Chart.yaml`):**
```yaml
apiVersion: v2
name: my-app
version: 1.0.0
dependencies:
- name: redis
  version: "17.x.x"
  repository: "https://charts.bitnami.com/bitnami"
  condition: redis.enabled
```

### Различия в синтаксисе команд

**Установка релиза:**
*   **v2:** `helm install stable/mysql --name my-db` (флаг `--name`).
*   **v3/v4:** `helm install my-db bitnami/mysql` (имя — позиционный аргумент).
*   **v3/v4 (автогенерация):** `helm install --generate-name bitnami/mysql`.

**Репозитории:**
*   **v2/v3:** Работа с HTTP-индексами (`helm repo add`).
*   **v4:** OCI-реестры стали стандартом де-факто. `helm registry login` требует только домен.

### Работа с CRD (Custom Resource Definitions)

В **Helm 2** CRD были обычными шаблонами. Если чарт создавал CRD и ресурс этого типа одновременно, Helm часто падал с ошибкой, так как API-сервер еще не знал о новом типе ресурса.

В **Helm 3 и v4** введена директория `crds/`:
1.  Манифесты из `crds/` устанавливаются **первыми**, до рендеринга любых шаблонов.
2.  **Важно:** Helm не обновляет и не удаляет CRD из этой директории при обновлении или удалении релиза. Это сделано для защиты данных: удаление CRD в Kubernetes приводит к немедленному удалению всех объектов этого типа во всем кластере.

### Библиотечные чарты (Library Charts)

Введены в Helm 3. Позволяют создавать общие шаблоны-хелперы, которые не разворачиваются как самостоятельные приложения.
```yaml
# Chart.yaml библиотечного чарта
apiVersion: v2
name: common-lib
type: library  # Ключевое поле
version: 1.0.0
```

### Миграция v2 → v3

**Подготовка:**
1.  Убедитесь, что все чарты используют `apiVersion: v2` в `Chart.yaml` или готовы к конвертации.
2.  Проверьте, что нет зависимостей от Tiller-side логики (например, скриптов, обращающихся к Tiller напрямую).

**Выполнение миграции:**
```bash
# 1. Установите плагин helm-2to3 (работает на v3/v4 для извлечения данных)
helm plugin install https://github.com/helm/helm-2to3.git

# 2. Выполните миграцию конкретного релиза
helm 2to3 convert my-release -n prod

# 3. Проверьте, что релиз виден в v3/v4
helm list -n prod
# → my-release   1    ...  ...

# 4. Проверьте, что Tiller отсутствует
kubectl get pods -n kube-system -l app=tiller
# → No resources found
```

**Валидация:**
```bash
# Сравните историю ревизий
helm history my-release -n prod

# Выполните dry-run
helm upgrade my-release ./my-chart --dry-run -n prod
```

### Миграция v3 → v4

**Подготовка:**
1.  Обновите бинарный файл Helm до v4.
2.  Проверьте совместимость плагинов: классические бинарные плагины работают, но рекомендуется мигрировать на WASM.
3.  Убедитесь, что Kubernetes-кластер поддерживает SSA (Kubernetes 1.18+).

**Выполнение миграции:**
```bash
# 1. Обновите Helm
# Linux:
curl https://baltocdn.com/helm/signing.asc | gpg --dearmor | sudo tee /usr/share/keyrings/helm.gpg > /dev/null
sudo apt-get install apt-transport-https --yes
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/helm.gpg] https://baltocdn.com/helm/stable/debian/ all main" | sudo tee /etc/apt/sources.list.d/helm-stable-debian.list
sudo apt-get update
sudo apt-get install helm

# 2. Проверьте версию
helm version
# → version.BuildInfo{Version:"v4.2.0", ...}

# 3. Выполните upgrade релиза
helm upgrade my-release ./my-chart -n prod \
  --atomic \
  --wait \
  --timeout 10m

# При первом upgrade v4 автоматически выполнит SSA-захват полей
```

**Валидация SSA:**
```bash
# Проверьте, что ресурсы теперь имеют field manager=helm
kubectl get deployment my-release -n prod -o yaml | grep -A5 managedFields
# → manager: helm
```

### Совместимость с Kubernetes

| Версия Helm | Минимальная версия K8s | Рекомендуемая версия K8s | Особенности |
| :--- | :--- | :--- | :--- |
| **v2** | 1.4 | 1.10+ | Требует RBAC-enabled кластер для Tiller |
| **v3** | 1.14 | 1.20+ | Полный отказ от Tiller, three-way merge |
| **v4** | 1.18 | 1.26+ | SSA, WASM-плагины, OCI-native |

**Практическое правило:** Для production-сред 2026 года используйте Helm v4 с Kubernetes 1.26+. Helm v3 допустим до июля 2026 (EOL).

### Настройка CI/CD под версии Helm

**Helm v2 (устаревший):**
```yaml
# .gitlab-ci.yml (legacy)
deploy:
  image: helm:v2
  script:
    - helm init --client-only
    - helm upgrade --install my-app stable/my-app --namespace prod
```

**Helm v3/v4 (современный):**
```yaml
# .gitlab-ci.yml
deploy:
  image: alpine/helm:latest
  script:
    - helm repo add my-repo https://charts.example.com
    - helm upgrade --install my-app my-repo/my-app \
        --namespace prod \
        --values values.yaml \
        --atomic \
        --wait \
        --timeout 10m
```

**Ключевые изменения в пайплайне:**
1.  **Удалён `helm init`** — больше не нужно разворачивать Tiller.
2.  **Добавлен `kubeconfig`** — авторизация через ServiceAccount-токен или `kubectl config`.
3.  **Добавлены `--atomic`/`--wait`** — атомарные деплои с автоматическим откатом.
4.  **Для v4 добавлен `--server-side`** — включение SSA (по умолчанию в v4, но явный флаг улучшает читаемость).

### Air-gapped миграция

В изолированных сетях (on-premise, банк, госсектор) миграция имеет особенности:

**v2 → v3 в air-gapped:**
```bash
# На машине с интернетом: скачайте плагин helm-2to3
curl -L https://github.com/helm/helm-2to3/archive/refs/tags/v0.x.x.tar.gz -o 2to3.tar.gz

# Перенесите архив в air-gapped сеть
scp 2to3.tar.gz jump-host:/tmp/

# Установите плагин локально
helm plugin install /tmp/helm-2to3

# Выполните миграцию
helm 2to3 convert my-release -n prod
```

**v3 → v4 в air-gapped:**
```bash
# На машине с интернетом: скачайте Helm v4 бинарник
curl -L https://get.helm.sh/helm-v4.2.0-linux-amd64.tar.gz -o helm.tar.gz

# Перенесите в air-gapped сеть
scp helm.tar.gz jump-host:/tmp/

# Установите
tar -zxvf helm.tar.gz
sudo mv linux-amd64/helm /usr/local/bin/helm

# Примените к релизам
helm upgrade my-release ./chart -n prod --atomic --wait
```

---

## Устранение неисправностей

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Error: tiller not found` | Helm 2 пытается использовать Tiller, но он не развёрнут | Установите Helm 3/4; Tiller удалён насовсем |
| `Error: release: "xxx" already exists` при migrate | Release Storage v2 (ConfigMap) конфликтует с v3 (Secret) | Запустите `helm 2to3 convert` до установки v3 |
| `Error: incompatible versions` | `Chart.yaml` имеет `apiVersion: v1`, а Helm v3/v4 требует `v2` | Обновите `apiVersion` и секцию `dependencies` |
| `Error: failed to download` (air-gapped) | Helm пытается тянуть зависимости из интернета | Используйте `helm dependency build` + `helm package` на сборной машине |
| `Error: Apply failed due to conflicts` | SSA конфликтует с другим контроллером | `kubectl get <resource> -o yaml` → `managedFields`; используйте `--force-conflicts` если Helm должен владеть полем |
| `Error: chart "xxx" not found` | Репозиторий не добавлен или не обновлён | `helm repo add`, `helm repo update`; проверьте `helm repo list` |
| `Error: UPGRADE FAILED: another operation is in progress` | Предыдущая операция не завершилась | `helm history <release>`; проверьте `kubectl get secrets -n <ns>` |
| `Error: INSTALLATION FAILED: failed post-renderer` | Ошибка в пост-рендерере (v4 требует `postrenderer/v1`) | Проверьте вывод `--debug`; убедитесь, что плагин типа `postrenderer/v1` установлен |

---

## Лучшие практики

1.  **Запрет на Tiller:** Никогда не разворачивайте Tiller в новых кластерах. Если обнаружен Tiller — мигрируйте на v3/v4 немедленно.
2.  **Атомарные деплои:** Всегда используйте `--atomic --wait --timeout 10m --cleanup-on-fail` в production. Это защищает от частично применённых релизов.
3.  **SSA по умолчанию:** В Helm v4 не отключайте SSA. Используйте `--force-conflicts` только при осознанном захвате полей после анализа `managedFields`.
4.  **Фиксация версий:** Используйте `helm upgrade --install` вместо отдельных `install`/`upgrade`. Это обеспечивает идемпотентность.
5.  **Валидация перед деплоем:** Внедрите `helm lint` + `helm template` + `kubeconform` в CI/CD на этапе PR.
6.  **Миграция по namespace:** При миграции v2→v3 мигрируйте релизы по одному namespace за раз, чтобы минимизировать риск.
7.  **Тестирование миграции:** Для критических релизов создайте staging-копию кластера и выполните полную миграцию там перед production.

---

## Ограничения и особенности

1.  **SSA и устаревшие API:** Некоторые старые версии Kubernetes (<1.18) не поддерживают полный функционал SSA и Field Ownership. При миграции на Helm v4 в кластерах с устаревшими API требуется предварительное обновление Kubernetes.
2.  **Пост-рендереры:** В v4 только плагины типа `postrenderer/v1`. Прямые пути к shell-скриптам больше не поддерживаются.
3.  **WASM-плагины:** Не все плагины v3 имеют портированные версии для WASM. Для ресурсоёмких операций (I/O, CPU-bound) могут требоваться классические плагины.
4.  **OCI в Helm v3:** OCI-реестры стали GA только в v3.8. Для версий v3.0–v3.7 требуется явное включение экспериментального флага.
5.  **Drift detection:** Helm v4 не исправляет дрейф автоматически. При расхождении между чартом и кластером требуется явный `helm upgrade` с корректным манифестом.
6.  **CRD не обновляются:** Helm никогда не обновляет и не удаляет CRD из директории `crds/` — это предотвращает потерю данных, но требует ручного управления при обновлении схемы CRD.

---

## Дополнительная информация

### Миграция и совместимость

*   **v2 → v3:** Использовался плагин `helm-2to3`. В 2026 году актуально только для извлечения данных из старых ConfigMaps в `kube-system`.
*   **v3 → v4:** Переход бесшовный для 99% чартов. Требуется обновление бинарного файла и, возможно, обновление плагинов до WASM-версий.
*   **Server-Side Apply:** При первом запуске Helm v4 на релизе, созданном v3, Helm автоматически выполнит "захват" полей (ownership transfer) в Kubernetes.

### Полезные ссылки

*   [Обзор Helm](./helm_overview.md) — архитектура v4 и установка.
*   [Структура чарта](./helm_chart_structure.md) — подробности `Chart.yaml` и `values.yaml`.
*   [Плагины Helm](./helm_plugins.md) — детали работы с WASM в v4.
*   [Блог Helm: Релиз v4](https://helm.sh/blog/helm-4-released/) — анонс и breaking changes.

См. также:
*   [Команды и рабочий процесс](./helm_commands_and_workflow.md)
*   [Безопасность Helm](./Advanced/security_best_practices.md)
*   [Паттерны и устранение неисправностей](./Advanced/patterns_troubleshooting.md)
*   [Управление версиями релизов](./helm_release_versioning.md)
