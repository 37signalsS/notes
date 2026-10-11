# Безопасность Java-образов: анализ угроз и методы укрепления (Hardening)

**Актуально для:** Java 25 LTS, Docker Engine 29.x, Linux (ядро 5.4+ с cgroups v2 и поддержкой user namespaces).

## Предварительные требования

- **Docker Engine:** 29.x с включённым BuildKit (`DOCKER_BUILDKIT=1` по умолчанию).
- **JDK:** Java 25 LTS для этапа сборки. В продакшене допустимы JLink-кастомные JRE или образы Wolfi/Chainguard.
- **Linux:** хост с включёнными cgroups v2 и `user.max_user_namespaces > 0`.
- **Инструменты сканирования:** Trivy, Syft, Docker Scout для SCA и проверки SBOM.
- **Система сборки:** Maven 3.9+ (`pom.xml` с зафиксированными версиями) или Gradle 8+ (`gradle.lockfile`).
- **Утилиты для аудита:** `jid` (JSON-инспектор для SBOM), `jq`, `docker buildx imagetools`.

## Определения

- **Бронебойный (Armored) образ:** Концепция создания контейнерного образа с минимально возможной поверхностью атаки, нулевым количеством известных уязвимостей (Zero CVE) и встроенными механизмами защиты на уровне рантайма (JVM).
- **Сценарии эксплуатации (Attack Vectors):** Специфичные для Java способы компрометации, включая десериализацию недоверенных данных, атаки через Java-агенты (например, OpenTelemetry) и подмену библиотек в цепочке поставок.
- **Serialization Filters (JEP 290/415):** Механизм JVM, позволяющий ограничивать классы, которые могут быть десериализованы, предотвращая атаки типа "gadget chains".
- **Modularity (JEP 261):** Система модулей Java (JPMS), обеспечивающая строгую инкапсуляцию API и позволяющая исключать неиспользуемые части JDK для снижения количества уязвимостей.
- **Axiom Linux Base:** Специализированный hardened-образ базовой ОС (на базе Axiom Linux), оптимизированный для работы с Java и обеспечивающий отсутствие уязвимостей на момент выпуска.
- **Hermetic builds (Герметичные сборки):** Сборка в изолированном окружении, где все зависимости (JAR, плагины) зафиксированы по хеш-суммам, а сетевой доступ во время компиляции полностью заблокирован.
- **SBOM (Software Bill of Materials):** Полный перечень компонентов ПО (библиотеки Maven/Gradle, модули JDK, пакеты ОС) с указанием версий и цифровых подписей.
- **VEX (Vulnerability Exploitability eXchange):** Документ, дополняющий SBOM и подтверждающий, что конкретная CVE не является эксплуатируемой в данном приложении (например, из-за использования фильтров десериализации).

## Базовые концепции

### Сценарии атак в Java-стеке (2025–2026)

Современные атаки сместились от эксплуатации уязвимостей в самой JVM к атакам на зависимости и инфраструктуру управления:

1.  **Компрометация цепочки поставок (Supply Chain):**
    *   **Type-squatting:** Использование похожих имен пакетов (например, `com.jackson` вместо `org.jackson`).
    *   **Poisoning Maven Central:** Публикация вредоносных обновлений.
    *   **MavenGate:** Перехват управления артефактами через истекшие домены владельцев групп.
2.  **Атаки через интерфейсы мониторинга и Java-агенты:**
    *   Агенты (OpenTelemetry, Datadog) работают с теми же привилегиями, что и приложение, и могут динамически изменять байт-код (Instrumenting).
    *   Подмена JAR-файла агента позволяет выполнить произвольный код до старта основного `main()` метода.
3.  **Утечки в снимках состояния (Snapshot Security):**
    *   При использовании **CRaC** или **Project Leyden** снимки памяти (checkpoints) могут содержать чувствительные данные (пароли, ключи шифрования, токены), находившиеся в Heap в момент создания дампа.
4.  **Эксплуатация десериализации:**
    *   Использование цепочек объектов (Gadget Chains) для выполнения RCE, несмотря на удаление `Security Manager`.

### Функции безопасности JDK 25 (LTS)

С выходом Java 25 (LTS) в 2025 году, механизмы защиты стали еще более интегрированными с контейнерной средой:

*   **Полное удаление Security Manager (JEP 486):** Более не поддерживается. Изоляция ресурсов (ФС, сеть) должна обеспечиваться исключительно на уровне ОС (Seccomp, AppArmor) и средств firewall (`iptables`, `nftables`).
*   **Инкапсуляция внутренних API:** Строгий запрет на `--add-opens` в Production-образах. Использование Reflection для обхода инкапсуляции блокируется по умолчанию.
*   **Верификация подписей модулей:** Улучшенные инструменты проверки целостности модулей JDK и прикладных JAR-файлов на этапе загрузки классов.

## Практические сценарии

### Сценарий 1: Снижение CVE через кастомизацию рантайма (JLink)

Удаление неиспользуемых модулей JDK напрямую коррелирует с уменьшением количества CVE. Например, модуль `java.desktop` (AWT/Swing) часто содержит уязвимости в нативных библиотеках рендеринга, которые не нужны серверным приложениям.

```bash
# Определение необходимых модулей для Java 25
jdeps --ignore-missing-deps --print-module-deps --recursive --multi-release 25 app.jar
# → com.example.myapp, java.base, java.desktop, ...
```

### Сценарий 2: Применение фильтров десериализации

Защита от RCE через глобальный фильтр. В Java 25 рекомендуется использовать динамические фильтры (JEP 415) для специфичных контекстов.

```bash
# Разрешаем только базовые типы и DTO приложения, блокируем всё остальное
java -Djdk.serialFilter="java.base/*;com.myapp.dto.*;!*" -jar app.jar
# → Фильтр активен: классы вне whitelist бросаются в сериализацию
```

### Сценарий 3: Харденинг Java-агентов

Для защиты от компрометации через агенты мониторинга необходимо ограничить доступ к их JAR-файлам и запретить избыточное переопределение кода.

1.  **Read-only монтирование:** Храните агенты в отдельном слое или volume с правами `ro`.
2.  **Ограничение Instrumentation:**
    ```bash
    # Запрет динамического добавления методов (защита от некоторых типов байт-код инъекций)
    java -XX:-AllowRedefinitionToAddMethods -javaagent:/opt/agents/otel.jar -jar app.jar
    # → Агент загружен, но не может добавлять новые методы в runtime
    ```

### Сценарий 4: Генерация SBOM и верификация зависимостей

Соответствие требованиям ФСТЭК (2025) требует наличия SBOM для каждого образа.

```xml
<!-- Пример CycloneDX Maven Plugin -->
<plugin>
    <groupId>org.cyclonedx</groupId>
    <artifactId>cyclonedx-maven-plugin</artifactId>
    <version>2.9.0</version>
    <executions>
        <execution>
            <phase>package</phase>
            <goals><goal>makeAggregateBom</goal></goals>
        </execution>
    </executions>
</plugin>
```
*   **Верификация:** Использование `pgpverify-maven-plugin` для проверки подписей всех зависимостей на этапе сборки.

## Инструменты и сканирование

### Сравнение сканеров уязвимостей

| Инструмент | Особенности | Сфера применения |
| :--- | :--- | :--- |
| **OSV Scanner** | Анализирует SBOM и иерархию `pom.xml`, находит CVE в транзитивных зависимостях. | Анализ зависимостей Java. |
| **Trivy** | Обнаруживает уязвимости в пакетах ОС и JAR-файлах, поддерживает сканирование секретов. | Универсальный CI/CD сканер. |
| **Tetragon (eBPF)** | Отслеживает системные вызовы JVM в Runtime. Может блокировать попытки `execve` (вызов shell) из процесса Java. | Runtime Security. |

**Рекомендация:** Используйте OSV Scanner для глубокого анализа Java-библиотек и Tetragon для мониторинга аномалий в реальном времени.

## Устранение неполадок

### Типичные ошибки и решения

1.  **`java.lang.OutOfMemoryError: Java heap space` в контейнере:**
    -   **Причина:** JVM использует размер heap по умолчанию хоста, а не лимита контейнера.
    -   **Решение:** Укажите `-XX:MaxRAMPercentage=75.0`. Проверьте лимиты через `docker inspect --format='{{.HostConfig.Memory}}' <container>`.

2.  **`java.io.StreamCorruptedException` при десериализации:**
    -   **Причина:** Сериализационный фильтр (JEP 290) блокирует легитимный класс.
    -   **Решение:** Добавьте класс в whitelist: `-Djava.io.SerialFilter="com.myapp.dto.MyClass;allow"` или используйте JEP 415 для контекстных фильтров.

3.  **`java.lang.ClassNotFoundException` после JLink:**
    -   **Причина:** `jdeps --print-module-deps` пропустил необходимый модуль (например, `java.instrument`).
    -   **Решение:** Явно укажите модули в `jlink --add-modules`. Проверьте через запуск приложения в обычном JDK с флагом `-verbose:class`.

4.  **`SecurityException: Unauthorized access` после удаления Security Manager (Java 25):**
    -   **Причина:** Приложение или библиотека использует устаревшие вызовы `System.setSecurityManager()`.
    -   **Решение:** Замените логику Security Manager на OS-level изоляцию (Seccomp, AppArmor). Для проверки добавьте `-Djava.security.manager=allow` и пересмотрите код.

5.  **Ошибка сборки GraalVM Native Image:**
    -   **Причина:** Reflection/Proxy/Resource конфигурация не включена для нативной компиляции.
    -   **Решение:** Включите `-H:+AddAllCharsets`, `-H:ReflectionConfigurationFiles`, сгенерируйте конфиг через `native-image-agent`.

### Диагностика

```bash
# Проверка Container Awareness JVM
docker exec <container_id> java -XshowSettings:system -version
# → Ищите: Operating System's architecture, Max. Memory, Processors

# Анализ классов в runtime
java -verbose:class -jar app.jar 2>&1 | grep "myapp"
# → Показывает загруженные классы: подтверждает или опровергает jdeps

# Проверка фильтра десериализации
java -Djava.io.SerialFilter="*=reject" -jar app.jar
# → Отклоняет все, кроме разрешённых: выявляет "бэкдоры" в сериализации
```

## Лучшие практики

1.  **Базовый образ:** Переход на **Wolfi** или **Axiom Linux Base** (0 CVE).
2.  **Non-root:** Обязательный запуск под UID > 1000.
3.  **Герметичность:** Использование Docker BuildKit с `--network=none` на этапе компиляции (требует предварительного прогрева кэша зависимостей).
4.  **Очистка снимков (CRaC):** Применение хуков `beforeCheckpoint` для затирания паролей и секретов в памяти перед созданием снимка.
5.  **ФСТЭК Compliance:** Разметка SBOM в соответствии с приказом 118 и информационным сообщением от 13.01.2025.
6.  **Фильтры десериализации:** Всегда включайте `-Djdk.serialFilter` на уровне production, даже если Security Manager удалён.
7.  **Agent Hardening:** Монтируйте агенты read-only, запрещайте `--add-opens` в production, используйте `-XX:-AllowRedefinitionToAddMethods`.
8.  **SCA в CI/CD:** Интегрируйте OSV Scanner или Trivy перед `docker build --push` для блокировки образов с CRITICAL уязвимостями.
9.  **Non-heap память:** Ограничьте Metaspace (`-XX:MaxMetaspaceSize=256m`) и Direct Memory (`-XX:MaxDirectMemorySize=512m`), чтобы предотвратить OOM через неприложные лимиты.
10. **Проверка подписей:** Используйте `cosign verify` + VSA attestation для проверки целостности образа перед запуском.

## Граничные случаи и ограничения

1.  **GraalVM Native Image и рефлексия:** Приложения с динамической загрузкой классов (Spring, Hibernate) требуют `reflect-config.json`. Автоматическая генерация через `native-image-agent` не покрывает все случаи.
2.  **CRaC и секреты в памяти:** Снимки `MemorySegment` и прямые буферы (ByteBuffer.allocateDirect) не очищаются автоматически. Необходимо использовать `Cleaner` или `Arrays.fill` перед `checkpoint()`.
3. **JLink и сервисы:** Модули с `ServiceLoader` (например, SLF4J) требуют явного указания в `--add-modules` — `jdeps` иногда пропускает сервис-провайдеры.
4.  **Alpine и musl:** JVM на базе Alpine (`musl libc`) имеет проблемы с JNI-библиотеками и потоками. Предпочитайте `glibc`-образы (Wolfi, Ubuntu) для продакшена.
5.  **Windows containers:** Container Awareness и cgroup-интеграция работают ограниченно. `-XX:MaxRAMPercentage` может не применяться на Windows Server Core.
6.  **Security Manager для legacy-кода:** Приложения, полагающиеся на Security Manager для sandboxing untrusted code, требуют рефакторинга на отдельные контейнеры с Seccomp/AppArmor.

## Дополнительная информация

### Смотрите также

- **[Dockerfile: Лучшие практики для Java](../Dockerfile/Docker_best_practices/java.md)** — практическая реализация сборок.
- **[SBOM для Docker-образов](./docker_sbom.md)** — методология учета зависимостей.
- **[Укрепление безопасности контейнеров](./container_hardening.md)** — общие принципы (Namespaces, Capabilities).
- **[Сканирование уязвимостей](./vulnerability_scanning.md)** — OSV Scanner, Trivy, EPSS.
- **[Безопасность цепочки поставок](../../Security/Supply_Chain_Security/overview.md)** — защита от type-squatting и MavenGate.

### Глубокое изучение

- **[JEP 290: Serialization Filtering](https://openjdk.org/jeps/290)** — источник механизма фильтров.
- **[JEP 486: Remove the Security Manager](https://openjdk.org/jeps/486)** — техническое обоснование удаления.
- **[CycloneDX Maven Plugin](https://cyclonedx.org/projects/cyclonedx-maven-plugin/)** — генерация SBOM для Maven.
