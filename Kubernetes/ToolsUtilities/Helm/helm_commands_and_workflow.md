# Основные команды и рабочий процесс Helm

Полный жизненный цикл управления Helm-приложениями: от поиска чарта до установки, отладки и удаления.

---

## Определения

| Термин | Описание |
|--------|----------|
| **Релиз** | Развёрнутый экземпляр чарта в Kubernetes-кластере. См. [Управление версиями релизов](./helm_release_versioning.md) |
| **helm upgrade --install** | Идемпотентная команда: устанавливает новый релиз или обновляет существующий |
| **helm template** | Локальный рендер шаблонов без обращения к кластеру. Ключевой инструмент отладки |
| **helm lint** | Валидация чарта на синтаксические ошибки и соответствие лучшим практикам |
| **helm rollback** | Откат релиза к предыдущей ревизии |

---

## Базовые концепции

### Идемпотентность развертывания

Команда `helm upgrade --install` устанавливает релиз, если он не существует, или обновляет существующий. Это обеспечивает предсказуемый результат при многократных вызовах, что критично для CI/CD (Continuous Integration/Continuous Deployment).

### Автоматическая генерация имени релиза

Флаг `--generate-name` автоматически создаёт уникальное имя релиза в формате `<chart-name>-<random-suffix>`. Удобно для тестовых развёртываний, когда имя не имеет значения:

```bash
helm install bitnami/mysql --generate-name
# → mysql-1717894532 (уникальное имя с рандомным суффиксом)
```

> **Ограничение:** `helm install --generate-name` только устанавливает релиз. Для последующих обновлений нужно знать сгенерированное имя и использовать `helm upgrade <имя>`.

### Управление значениями релиза

Значения, установленные через `--set`, сохраняются в Secret релиза и доступны для просмотра:

```bash
# Просмотр значений текущей ревизии
helm get values my-release -n prod

# Просмотр всех значений (включая defaults)
helm get values my-release -n prod --all
```

**Сброс кастомных значений:**

При обновлении релиза можно откатить значения, ранее установленные через `--set`, к значениям по умолчанию из чарта:

```bash
# Сброс всех --set значений к дефолтным из values.yaml чарта
helm upgrade my-release ./my-chart --reset-values -n prod
```

Флаг `--reset-values` удаляет все кастомные значения, сохранённые в Secret релиза, и использует только значения из текущего `values.yaml` (или файла, указанного через `-f`).

### Атомарность и ожидание

Helm гарантирует надежность развертываний с помощью флагов `--atomic` и `--timeout`. В случае сбоя (поды не переходят в состояние Ready), Helm автоматически откатывается к предыдущей стабильной версии.

### Поведение `helm install` по умолчанию

Команда `helm install` **не ждёт** запуска всех ресурсов перед завершением. Большинство чартов используют контейнерные образы размером 600+ МБ, загрузка и запуск которых может занять значительное время.

Для ожидания полной готовности всех ресурсов используйте:

```bash
# Ожидание готовности всех подов перед завершением
helm install myapp bitnami/wordpress --wait

# Атомарная установка с ожиданием и автоматическим откатом при сбое
helm install myapp bitnami/wordpress --atomic --timeout 10m
```

Флаг `--atomic` включает `--wait` и добавляет автоматический откат при достижении таймаута или сбое проверки готовности.

**Дополнительные флаги ожидания и поведения:**

| Флаг | Описание | Доступен для |
|------|----------|-------------|
| `--timeout <duration>` | Время ожидания готовности ресурсов. По умолчанию 5 минут. Увеличивайте для чартов с долгой инициализацией подов | `install`, `upgrade`, `rollback` |
| `--wait` | Ждёт, пока все поды перейдут в состояние `Ready`, PVC (PersistentVolumeClaim) будут забайнджены с PV (PersistentVolume), Deployment получит минимальное количество реплик (с учётом `maxUnavailable`), Service получит IP (Internet Protocol) (если `LoadBalancer`) | `install`, `upgrade`, `rollback` |
| `--wait-for-jobs` | Вместе с `--wait` — ждёт завершения Helm Jobs перед тем как считать релиз готовым | `install`, `upgrade` |
| `--atomic` | Включает `--wait` + автоматический откат к предыдущей ревизии при достижении таймаута или сбое | `install`, `upgrade` |
| `--no-hooks` | Пропускает выполнение Helm Hooks при установке/обновлении | `install`, `upgrade` |
| `--recreate-pods` | Пересоздаёт все поды (кроме принадлежащих Deployment). **Устарел** — для Deployment используйте стратегию `Recreate` в манифесте | `upgrade`, `rollback` |

> **Рекомендация:** Флаг `--atomic` полностью покрывает функциональность `--wait` и предпочтительнее для production-развёртываний, так как добавляет автоматический откат вместо ручной диагностики.

### Порядок создания ресурсов

Helm создаёт ресурсы Kubernetes в определённом порядке, зависящем от типа ресурса:

1. **Namespace** — пространство имён
2. **NetworkPolicy** — сетевые политики
3. **ResourceQuota** — квоты ресурсов
4. **LimitRange** — ограничения ресурсов
5. **PodSecurityPolicy / PodDisruptionBudget** — политики безопасности
6. **ServiceAccount** — учётные записи сервисов
7. **Secret** — секреты
8. **PersistentVolume / PersistentVolumeClaim** — хранилища
9. **ConfigMap** — конфигурационные карты
10. **Deployment / DaemonSet / StatefulSet / ReplicaSet** — контроллеры подов
11. **Service** — сервисы
12. **Ingress** — маршрутизация внешнего трафика

Этот порядок помогает избежать зависимостей между ресурсами, но не всегда гарантирует корректную последовательность — в некоторых случаях требуется ручное управление зависимостями через [Helm Hooks](./helm_hooks_and_tests.md).

### Источники для установки чарта

Команда `helm install` поддерживает установку чартов из различных источников. Подробнее об источниках чартов и работе с OCI (Open Container Initiative)-реестрами см. [Обзор Helm](./helm_overview.md).

```bash
# Из репозитория (добавленного через helm repo add)
helm install my-release bitnami/wordpress

# Из локального архива .tgz
helm install my-release ./wordpress-15.3.0.tgz

# Из распакованной директории чарта (предпочтительный способ для разработки)
helm install my-release ./wordpress/

# По полному URL (Uniform Resource Locator) архива чарта
helm install my-release https://example.com/charts/wordpress-15.3.0.tgz

# Из OCI-реестра
helm install my-release oci://registry.example.com/charts/wordpress --version 15.3.0
```

> **Рекомендация:** Для разработки и отладки предпочтительнее использовать распакованную директорию — это позволяет сразу видеть структуру чарта и вносить изменения. Для production — используйте репозитории или OCI-реестры с фиксацией версии через `--version`.

---

## Практические сценарии

### Управление приложениями: пример с kube-ops-view

* **Управление репозиториями**:
  * **Добавление**: `helm repo add stable https://charts.helm.sh/stable`
  * **Обновление**: `helm repo update`

* **Поиск чарта**:
  * **В Artifact Hub (глобальный поиск)**: `helm search hub kube-ops-view`
  * **В локальных репозиториях**: `helm search repo kube-ops-view`

* **Установка и кастомизация**:
    1. **Просмотр настроек**: `helm show values stable/kube-ops-view`
    2. **Кастомизация**: сохраните `values.yaml` для внесения изменений (`helm show values stable/kube-ops-view > values.yaml`).
    3. **Установка/Обновление**: примените изменения в кластере, используя `helm upgrade --install ops-view stable/kube-ops-view --namespace kube-system -f values.yaml --create-namespace --atomic`. Рекомендуется использовать плагин [helm-diff](./helm_plugins.md) для предпросмотра изменений.

* **Управление релизом**:
  * **Просмотр списка релизов**: `helm list -n kube-system`
  * **Проверка статуса релиза**: `helm status ops-view -n kube-system`
  * **Откат к предыдущей версии**: `helm rollback ops-view 1`
  * **Удаление релиза**: `helm uninstall ops-view -n kube-system`. **Важно**: удаляйте приложения только этой командой для корректного удаления всех связанных ресурсов (например, `ClusterRole`).

### Рабочий процесс разработки чарта

1. **Создание скелета чарта**:
    Команда `helm create <chart-name>` генерирует стандартную структуру директорий и файлов, включая `Chart.yaml`, `values.yaml` и примеры шаблонов.

    ```bash
    helm create my-chart
    ```

2. **Отладка и рендеринг шаблонов**:
    Команда `helm template` — ключевой инструмент разработчика. Рендерит шаблоны локально и выводит итоговые YAML (YAML Ain't Markup Language)-манифесты в консоль без обращения к кластеру.

    ```bash
    # Рендеринг с values по умолчанию
    helm template my-release ./my-chart

    # Рендеринг с кастомными values и выводом в файл
    helm template my-release ./my-chart -f my-values.yaml > rendered.yaml
    ```

3. **Переопределение `values.yaml`**:

    * **Файл со значениями (`-f` или `--values`)**: предпочтительный способ для множества изменений.

        ```bash
        helm install my-release ./my-chart -f my-values.yaml
        ```

    * **Прямое указание (`--set`)**: удобно для единичных изменений.

        ```bash
        helm install my-release ./my-chart --set replicaCount=5 --set image.tag="1.26.0"
        ```

    * **Синтаксис `--set` для сложных структур**:

      **Вложенные переменные** — используются точки для обращения к вложенным ключам:

      ```bash
      # Эквивалентно YAML:
      # mariadb:
      #   auth:
      #     database: "user0db"
      #     username: "user0"
      helm install my-release ./my-chart \
        --set mariadb.auth.database=user0db \
        --set mariadb.auth.username=user0
      ```

      **Списки (массивы)** — фигурные скобки `{}` для перечисления элементов:

      ```bash
      # Эквивалентно YAML:
      # servers:
      #   - nginx
      #   - apache
      #   - haproxy
      helm install my-release ./my-chart --set servers={nginx,apache,haproxy}
      ```

      **Доступ по индексу** — квадратные скобки `[]` для обращения к конкретному элементу массива:

      ```bash
      # Эквивалентно YAML:
      # servers:
      #   - port: 80
      #     host: example.com
      #   - port: 443
      #     host: secure.example.com
      helm install my-release ./my-chart \
        --set servers[0].port=80,servers[0].host=example.com \
        --set servers[1].port=443,servers[1].host=secure.example.com
      ```

      **Пустые значения и пустые массивы**:

      ```bash
      # Пустое значение (null)
      helm install my-release ./my-chart --set key=null

      # Пустой массив
      helm install my-release ./my-chart --set list=[]

      # Массив с пустым элементом
      helm install my-release ./my-chart --set list[0]=
      ```

      **Экранирование специальных символов** — обратный слеш `\` для корректной интерпретации запятых, точек и других символов внутри значений:

      ```bash
      # Значение с запятой (иначе будет интерпретировано как разделитель)
      helm install my-release ./my-chart --set name="value1\,value2"

      # Значение с точкой (иначе будет интерпретировано как вложенный ключ)
      helm install my-release ./my-chart --set host="host\.example\.com"
      ```

      > **Рекомендация:** `--set` удобен для быстрых изменений, но при сложной конфигурации предпочтительнее использовать `-f values.yaml` — это более читаемо и поддерживаемо.

4. **Валидация чарта**:

    ```bash
    helm lint ./my-chart
    ```

5. **Установка и удаление**:

    ```bash
    helm install my-release ./my-chart -n my-namespace --create-namespace
    helm uninstall my-release -n my-namespace
    ```

6. **Инспектирование локального чарта**:
    `helm pull stable/kube-ops-view --untar` скачивает и распаковывает архив чарта (`.tgz`) для локального изучения.

---

## Дополнительная информация

### Инспектирование чартов — `helm show`

Команда `helm show` позволяет просмотреть содержимое чарта без его установки:

```bash
# Только метаданные Chart.yaml
helm show chart bitnami/mysql
# → name, version, appVersion, description, dependencies...

# Только values.yaml
helm show values bitnami/mysql

# Все доступные данные чарта (Chart.yaml + values + README)
helm show all bitnami/mysql

# Чарт из локальной директории
helm show all ./my-chart/
```

Полезно для ознакомления с доступными параметрами чарта перед установкой.

### Удаление с сохранением истории

Флаг `--keep-history` при `helm uninstall` удаляет все ресурсы релиза из кластера, но сохраняет запись в истории:

```bash
helm uninstall myapp --keep-history
# → Ресурсы удалены, но helm history myapp показывает статус 'uninstalled'
```

Это позволяет в дальнейшем восстановить релиз через `helm install` с тем же именем, сохранив нумерацию ревизий. Без флага запись полностью удаляется из истории.

### Поиск чартов

Поиск чартов описан в разделе [Источники чартов](./helm_overview.md#источники-чартов).

**Artifact Hub** ([artifacthub.io](https://artifacthub.io)) — центральная площадка для поиска Helm-чартов. Содержит 14 000+ чартов с рейтингами (звёздочки) и информацией о последнем обновлении. При поиске через веб-интерфейс можно ориентироваться на популярность чарта по количеству звёзд и авторитетность автора.

> **Важно:** `helm search hub` без фильтра выводит все доступные чарты — результат может не поместиться в терминал. Рекомендуется использовать веб-интерфейс Artifact Hub или указывать ключевое слово для фильтрации.

**Установка чартов осуществляется на ваш страх и риск** — проверяйте источник и содержимое чарта перед развёртыванием.

Подробности о плагинах см. в [Helm Plugins](./helm_plugins.md). См. также [Практические сценарии чартов](./helm_chart_practical_scenarios.md) для production-рабочих процессов.
