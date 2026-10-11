# SBOM для Docker-образов

**Актуально для:** Docker Engine 29.x, Syft v1.52+, CycloneDX 1.7, SPDX 3.x. Docker Engine 28.x и ранее достигли EOL (май 2026).

## Определения

**SBOM (Software Bill of Materials) для Docker** — это машиночитаемый инвентарный перечень всех компонентов Docker-образа: прямых и транзитивных зависимостей, их версий, лицензий и идентификаторов — **PURL (Package URL)**, **CPE (Common Platform Enumeration)**. SBOM является фундаментом для процесса **SCA (Software Composition Analysis)**.

**Living SBOM** — концепция динамического графа зависимостей (актуальна для 2026 года), который обновляется на каждом этапе жизненного цикла: от сборки (Build-time SBOM) до эксплуатации (Runtime SBOM), отражая реально загруженные в память библиотеки.

**VEX (Vulnerability Exploitability eXchange)** — сопроводительный документ (профиль CycloneDX или SPDX), уточняющий статус уязвимости в конкретном контексте приложения. Позволяет официально заявить, что уязвимость "не влияет" (not affected), что радикально снижает количество ложных срабатываний при сканировании.

**CBOM (Cryptographic BOM)** — специализированный раздел SBOM (стандарт CycloneDX 1.6+), содержащий сведения об используемых криптографических алгоритмах и ключах. Необходим для аудита устойчивости к квантовым угрозам (PQC).

См. подробнее: **[анализ зависимостей и SBOM](../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md)**.

## Предварительные требования

- **Docker Engine:** 29.x с включенным BuildKit (`DOCKER_BUILDKIT=1` по умолчанию). Docker 28.x и ранее достигли EOL (май 2026).
- **Инструменты генерации:** `Syft v1.52+` (установка: `curl -sSfL https://get.anchore.io/syft | sudo sh -s -- -b /usr/local/bin`), `Trivy` для сканирования.
- **Реестр:** Harbor 2.11+, GitHub Container Registry, или любой реестр с поддержкой **OCI 1.1 Referrers API** для прикрепления SBOM к образу.
- **Подпись:** `Cosign` или `Notation` для подписания аттестаций SBOM.
- **Права:** Доступ к реестру для загрузки образов и аттестаций. В CI/CD — сервисный аккаунт с правами `write` на реестр и `read` на артефакты.

**Валидация:**
```bash
# Проверка версии Syft
syft --version
# → syft version: v1.52.0

# Проверка поддержки Referrers API в реестре
curl -v -H "Accept: application/vnd.docker.distribution.manifest.v2+json" \
  https://my-registry.example.com/v2/my-image/manifests/latest
# → В заголовках должен присутствовать Header: Link: </v2/my-image/manifests/sha256:...>; rel="referrers"
```

## Базовые концепции

Безопасность цепочки поставок в 2026 году требует прозрачности состава ПО на всех этапах.

### Стандартные форматы

| Формат | Версия | Фокус | Примечание |
| :--- | :--- | :--- | :--- |
| **CycloneDX** | 1.7 | Безопасность, VEX, CBOM | Основной формат для автоматизации DevSecOps. |
| **SPDX** | 3.0 | Юридический комплаенс, лицензии, Linked Data | Модульная архитектура (JSON-LD), стандарт ISO. |

### Современные инструменты и процессы (2026)

1. **Генерация**: **Syft v1.52+** и **Trivy** являются индустриальными стандартами. `docker buildx --sbom` интегрирует генерацию прямо в процесс сборки BuildKit.
2. **Аттестация и хранение**: SBOM подписывается через **Cosign** и хранится как аттестация. В 2026 году активно используется **OCI 1.1 Referrers API**, позволяющий прикреплять SBOM к образу без изменения его основного дайджеста.
3. **Верификация (VSA)**: **Verification Summary Attestation** — итоговый документ, подтверждающий, что SBOM был сгенерирован и проверен сканерами в соответствии с политиками организации.
4. **ASPM (Application Security Posture Management)**: Платформы типа **Docker Scout** или **Dependency-Track** агрегируют SBOM для непрерывного мониторинга новых CVE.

### Требования ФСТЭК (РФ, 2025)

Для сертификации средств в контейнерном исполнении (Инф. сообщение от 13.01.2025) установлены специфические требования к SBOM:
*   **Формат:** CycloneDX версии 1.6 и выше.
*   **Обогащение (Properties):** Обязательная разметка каждого компонента по его отношению к функциям безопасности и поверхности атаки (бинарные поля).
*   **Поле `ghost provided by`:** Используется для подтверждения, что компонент заимствован из сертифицированной ОС.
*   **Валидация:** Формальная проверка состава с помощью скриптов (verifier) от **ЦКИ СП РАН (ИСП РАН)**.

Подробнее: **[Сертификация ФСТЭК для контейнеров](../../Linux/Security/Fstec/container_certification.md)**.

## Практические сценарии

### 1. Глубокая генерация SBOM с помощью Syft v1.52+

Syft анализирует слои образа, пакетные менеджеры (npm, go mod, pip) и даже бинарные файлы.

```bash
# Генерация Living SBOM в формате CycloneDX 1.7 JSON
syft image my-app:latest -o cyclonedx-json > sbom.json
# → Файл sbom.json содержит bomFormat: "CycloneDX", specVersion: "1.7"

# Анализ конкретной директории с генерацией SPDX 3.0
syft dir:./src -o spdx-json > project.spdx.json
# → Файл project.spdx.json содержит spdxVersion: "SPDX-3.0"

# Проверка количества компонентов
jq '.components | length' sbom.json
# → 42 (количество обнаруженных пакетов)
```

### 2. Сборка с аттестациями (BuildKit + OCI 1.1)

```bash
# Сборка с генерацией SBOM, Provenance (происхождение) и загрузкой в реестр
docker buildx build \
  --tag my-registry/my-app:1.2.0 \
  --sbom=true \
  --provenance=mode=max \
  --push \
  .
# → SBOM и Provenance прикреплены к образу как аттестации через OCI 1.1 Referrers API

# Проверка аттестаций через CLI
docker buildx imagetools inspect my-registry/my-app:1.2.0 --format '{{ json .SBOM }}'
# → Вывод JSON-структуры SBOM с полями bomFormat, specVersion, components
```

### 3. Использование Docker Scout для анализа аттестаций

Docker Scout автоматически анализирует аттестации образов в реестре и сопоставляет их с политиками безопасности.

```bash
# Анализ состава и рисков на основе прикрепленного SBOM
docker scout cves my-app:latest
# → Таблица CVE с полями: CVE ID, Severity, Package, Version, Fix Version

# Сравнение состава двух образов (drift analysis)
docker scout compare my-app:v1 --to my-app:v2
# → Отчет о различиях: добавленные/удаленные/измененные компоненты
```

## Best Practices

- **SBOM на каждый образ:** Генерация SBOM должна быть обязательным этапом CI/CD. Подписывайте SBOM через Cosign и прикрепляйте через OCI 1.1 Referrers API. Блокируйте deployment образов без валидного SBOM.
- **Фиксация по дайджесту:** Используйте `image@sha256:...` вместо тегов при сканировании SBOM. Теги могут быть переназначены, что приведет к несоответствию SBOM и образа.
- **Минимальные образы:** Distroless и Chainguard образы генерируют SBOM с минимальным количеством компонентов, что упрощает аудит и снижает количество CVE.
- **Цикл VEX:** Внедрите процесс анализа уязвимостей. Не все CVE эксплуатируемы — используйте VEX (см. `vulnerability_scanning.md`) для фильтрации ложных срабатываний.
- **Хранение SBOM:** Храните SBOM минимум 12 месяцев (требование EU CRA). Используйте реестр с нативной поддержкой Referrers API (Harbor 2.11+, GHCR).
- **Валидация перед деплоем:** Настройте admission controller (Kyverno/OPA) для проверки наличия подписанного SBOM и отсутствия критических CVE перед запуском контейнера.
- **Сканирование базового образа:** Генерируйте SBOM для базовых образов (distroless, alpine) отдельно и включайте их в baseline. Сравнивайте SBOM базового образа при обновлении.

## Troubleshooting

- **`syft: command not found`:**
  - **Причина:** Syft не установлен или не в PATH.
  - **Решение:** Установите через `curl -sSfL https://get.anchore.io/syft | sudo sh -s -- -b /usr/local/bin`. Проверьте: `syft --version`.

- **`Attestation not found` при `docker buildx imagetools inspect`:**
  - **Причина:** SBOM не был прикреплен к образу. Возможные причины: сборка без `--sbom=true`, отсутствие `--push` при сборке, реестр не поддерживает Referrers API.
  - **Решение:** Пересоберите с флагами `--sbom=true --push`. Убедитесь, что реестр поддерживает Referrers API. Для локальной проверки используйте `--output type=docker`.

- **`syft` не распознает пакеты в Distroless образе:**
  - **Причина:** Distroless образы не содержат менеджеров пакетов. Syft анализирует файловую систему и может не найти стандартные пакеты.
  - **Решение:** Это ожидаемое поведение. Distroless SBOM будет содержать только языковые зависимости. Для полного аудита используйте multi-stage сборку с промежуточным образом для генерации SBOM.

- **`docker scout` не находит SBOM для образа:**
  - **Причина:** Образ не имеет прикрепленного SBOM, или Docker Scout не имеет доступа к реестру.
  - **Решение:** Убедитесь, что SBOM был загружен в реестр вместе с образом. Проверьте аутентификацию: `docker scout login`. Используйте `docker scout quickview` для диагностики.

- **SBOM содержит уязвимый компонент, но приложение его не использует (ложное срабатывание):**
  - **Причина:** Сканер находит CVE в библиотеке, но уязвимая функция не вызывается в коде приложения.
  - **Решение:** Создайте VEX-отчет со статусом `not_affected` (см. `vulnerability_scanning.md`). Для автоматического анализа достижимости используйте Trivy с флагом `--show-vulnerability-reachability`.

- **CycloneDX и SPDX SBOM различаются по составу компонентов:**
  - **Причина:** Разные форматы по-разному обрабатывают зависимости и метаданные. Конвертация между форматами может привести к потере информации.
  - **Решение:** Генерируйте SBOM в нужном формате напрямую (`syft -o cyclonedx-json` или `syft -o spdx-json`). Избегайте конвертации для compliance-документов.

## Дополнительная информация

**Граничные случаи и ограничения:**

- **Multi-arch образы (manifest list):** Syft не поддерживает анализ multi-arch manifest list напрямую. Генерируйте SBOM для каждого архитектурного варианта отдельно: `docker buildx imagetools inspect --format '{{json .Manifest}}' image:tag` и `syft -o cyclonedx-json <image>:<tag>@<digest>`.
- **Distroless образы:** Не содержат менеджеров пакетов (apk, dpkg). Syft анализирует файловую систему и генерирует SBOM только с языковыми зависимостями. Это ожидаемое поведение, а не ошибка.
- **OCI 1.1 Referrers и старые реестры:** Не все реестры поддерживают Referrers API. Harbor 2.11+, GHCR и Docker Hub поддерживают. Для старых реестров используйте теги-пустышки (`.sbom`, `.att`) как fallback.
- **SBOM для бинарных файлов (Go, Rust):** Статически скомпилированные бинарники не оставляют следов в менеджере пакетов. Syft анализирует ELF-заголовки и генерирует PURL вида `pkg:generic/<name>@<version>`. Для точности добавляйте metadata через `--config auto`.
- **Конвертация CycloneDX ↔ SPDX:** При конвертации теряются VEX-данные и CBOM-свойства. Генерируйте SBOM в целевом формате напрямую. Используйте конвертацию только для совместимости со старыми инструментами.

**Связанные документы:**
- **[Анализ зависимостей и SBOM](../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md)** — общая теория SCA и концепция Living SBOM.
- **[Сертификация ФСТЭК для контейнеров](../../Linux/Security/Fstec/container_certification.md)** — регуляторные требования к составу образов и SBOM.
- **[Сканирование уязвимостей](./vulnerability_scanning.md)** — практическое использование Trivy и Grype.
- **[Подписание и верификация образов](./image_signature_and_verification.md)** — аттестации, Cosign и VSA.
- **[Безопасность цепочки поставок](../../Security/Supply_Chain_Security/overview.md)** — уровни SLSA и защита пайплайнов.

**Внешние ресурсы:**
- **CycloneDX Specification (v1.7):** [cyclonedx.org](https://cyclonedx.org/).
- **SPDX Standard (v3.0):** [spdx.dev](https://spdx.dev/).
- **OCI 1.1 Referrers API Guide:** [opencontainers.org](https://opencontainers.org/).
- **Docker Scout Docs:** [docs.docker.com/scout/](https://docs.docker.com/scout/).

**Инструменты:** `Syft` (генерация v1.52+), `Trivy` (сканирование SBOM и VEX), `Grype` (глубокая интеграция с SBOM), `Cosign` (подпись аттестаций), `Docker Scout` (ASPM платформа).
