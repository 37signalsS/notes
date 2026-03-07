# Управление версиями релизов

Helm управляет версиями на трёх уровнях: версия чарта, версия приложения и ревизия релиза в кластере.

---

## Определения

| Сущность | Где определяется | Формат | Назначение |
|----------|------------------|--------|------------|
| **Версия чарта** | `Chart.yaml: version` | SemVer (1.4.2) | Идентификация пакета; выбор версии при установке из репозитория |
| **Версия приложения** | `Chart.yaml: appVersion` | Свободный (обычно SemVer) | Маркер версии разворачиваемого ПО; информационное поле |
| **Ревизия релиза** | Secret/ConfigMap в namespace релиза | Целое число (1, 2, 3…) | Снимок состояния при каждой операции `upgrade`/`rollback` |

**Хранилище истории:**

- Helm 3: Secrets с именем `sh.helm.release.v1.<release-name>.v<revision>` в namespace релиза
- Helm 2: ConfigMaps в namespace `kube-system`

См. [Сравнение Helm v2 и v3](./helm_v2_vs_v3.md) для деталей различий хранения.

---

## Основные концепции

### Семантическое версионирование (SemVer)

Версии чартов следуют формату `MAJOR.MINOR.PATCH`:

- **MAJOR** — несовместимые изменения
- **MINOR** — новая функциональность, обратно совместимая
- **PATCH** — исправления ошибок

**Диапазоны версий в зависимостях:**

```yaml
dependencies:
  - name: redis
    version: "^17.1.0"    # >=17.1.0 и <18.0.0
  - name: postgresql
    version: "~12.1.0"    # >=12.1.0 и <12.2.0
  - name: mysql
    version: ">=8.0.0"    # 8.0.0 и выше
```

### `version` vs `appVersion`: Best Practices

Хотя `appVersion` является информационным полем, лучшей практикой в CI/CD является строгая синхронизация версий.

- **`appVersion`** должна соответствовать версии развертываемого приложения (например, тегу Docker-образа).
- **`version`** (версия чарта) должна инкрементироваться (обычно `PATCH`-часть) при **любом** изменении, включая:
  - Изменения в шаблонах (`templates/`).
  - Добавление новых параметров в `values.yaml`.
  - **Обновление `appVersion`**.

Этот подход гарантирует, что для каждой версии приложения существует уникальный, неизменяемый артефакт чарта. Это позволяет точно отслеживать, какая версия чарта развертывает какую версию приложения, и обеспечивает надежные откаты.

**Пример в CI/CD:**
При сборке новой версии приложения `v1.5.0`:

1. CI-пайплайн собирает Docker-образ `my-app:v1.5.0`.
2. Затем он обновляет `Chart.yaml`:
    - `appVersion` устанавливается в `"1.5.0"`.
    - `version` инкрементируется, например, с `1.1.2` до `1.1.3`.
3. Новая версия чарта публикуется в репозиторий.

### История релизов

Каждая операция `helm upgrade` или `helm rollback` создаёт новую ревизию. История хранит:

- Манифесты, отправленные в кластер
- Значения параметров (values)
- Информацию о дате и статусе

**Преимущества:**

- Аудит изменений
- Восстановление предыдущих состояний
- Анализ диффов между версиями

### Зависимости и lock-файл

При использовании зависимостей Helm фиксирует точные версии в `Chart.lock`:

```yaml
# Chart.yaml
dependencies:
  - name: redis
    version: "^17.1.0"
    repository: https://charts.bitnami.com/bitnami
```

```bash
# Обновление зависимостей и создание Chart.lock
helm dependency update

# Сборка зависимостей по Chart.lock
helm dependency build
```

См. [Структура Helm-чарта](./helm_chart_structure.md) для подробностей о файловой структуре.

---

## Практические сценарии

### Просмотр и анализ истории

```bash
# История релиза
helm history my-release -n prod

# Детали конкретной ревизии
helm get values my-release -n prod --revision 7
helm get manifest my-release -n prod --revision 7

# Показать все значения текущей ревизии
helm get values my-release -n prod --all

# Показать заметки релиза
helm get notes my-release -n prod
```

### Откат релиза

```bash
# Откат к конкретной ревизии
helm rollback my-release 7 -n prod

# Откат с ожиданием и таймаутом
helm rollback my-release 7 -n prod --wait --timeout 5m

# Восстановление после удаления с сохранением истории
helm uninstall my-release -n prod --keep-history
helm rollback my-release 0 -n prod  # 0 — последняя ревизия
```

### Управление глубиной истории

```bash
# Ограничение количества хранимых ревизий при обновлении
helm upgrade myapp bitnami/nginx --history-max 10 -n prod

# Удаление с сохранением истории
helm uninstall myapp -n prod --keep-history
```

### Продвижение через окружения

```bash
# Установка конкретной версии в Dev
helm upgrade --install app app-chart \
  -f values/dev.yaml \
  --version 2.3.1 \
  -n dev

# Продвижение той же версии в Staging
helm upgrade --install app app-chart \
  -f values/staging.yaml \
  --version 2.3.1 \
  -n stage

# Продвижение в Production с дополнительными проверками
helm upgrade --install app app-chart \
  -f values/prod.yaml \
  --version 2.3.1 \
  --wait \
  --timeout 10m \
  --atomic \
  -n prod
```

### Проверка изменений перед обновлением

```bash
# Просмотр диффа перед обновлением
helm diff upgrade myapp bitnami/nginx -n prod

# Сравнение двух ревизий
helm get manifest myapp -n prod --revision 5 > rev5.yaml
helm get manifest myapp -n prod --revision 6 > rev6.yaml
diff rev5.yaml rev6.yaml
```

### Best practices

- **Пиннинг версий**: Явно указывайте версии чартов в production (`--version X.Y.Z`)
- **Атомарность**: Используйте `--atomic` для автоматического отката при сбое
- **Контроль истории**: Ограничивайте `--history-max` для экономии ресурсов (рекомендуется 10-20)
- **Хранение values**: Держите `values` файлы под версионным контролем
- **Тестирование**: Проверяйте обновления в staging перед production

---

## Дополнительная информация

- [Обзор Helm](./helm_overview.md) — общие концепции, жизненный цикл релиза
- [Структура Helm-чарта](./helm_chart_structure.md) — Chart.yaml, зависимости, Chart.lock
- [Сравнение Helm v2 и v3](./helm_v2_vs_v3.md) — различия в хранении истории релизов
