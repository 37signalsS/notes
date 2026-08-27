# Security Scanning в Mobile CI/CD

## Определения

**SAST (Static Application Security Testing)** — статический анализ исходного кода на наличие уязвимостей. Общие инструменты (Semgrep, CodeQL) см. в **[SAST Overview](../DevSecOps/sast_overview.md)**. В.mobile-контексте: **SwiftLint** (iOS), **Detekt** (Android).

**SCA (Software Composition Analysis)** — анализ зависимостей проекта на известные уязвимости (CVE). Общие инструменты (Trivy, Snyk) см. в **[SAST/DAST CI/CD Integration](../DevSecOps/sast_dast_cicd_integration.md)**. В.mobile-контексте: **OWASP Dependency-Check** с мобильной конфигурацией.

**DAST (Dynamic Application Security Testing)** — тестирование приложения в runtime. Общие инструменты (OWASP ZAP) см. в **[DAST Overview](../DevSecOps/dast_overview.md)**. В.mobile-контексте: **MobSF** (Mobile Security Framework).

**Shift Left Security** — подход, при котором проверки безопасности переносятся на ранние этапы разработки. Подробнее см. в **[DevSecOps Overview](../DevSecOps/devsecops_overview.md)**.

---

## Базовые концепции

### Типы уязвимостей в Mobile

| Тип | iOS | Android | Критичность |
|:---|:---|:---|:---|
| **Dependency CVE** | CocoaPods, SPM | Gradle, Maven | Высокая |
| **Insecure Storage** | Keychain, UserDefaults | SharedPreferences, SQLite | Критическая |
| **Insecure Network** | HTTP, Certificate Pinning | HTTP, SSL/TLS | Высокая |
| **Code Injection** | JavaScript Core | WebView | Критическая |
| **Hardcoded Secrets** | API Keys, Tokens | API Keys, Tokens | Критическая |
| **Weak Crypto** | MD5, SHA1 | MD5, SHA1 | Средняя |

### Пайплайн безопасности (DevSecOps)

```
┌──────────────────────────────────────────────────────────┐
│                    CI/CD Pipeline                         │
│                                                          │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐ │
│  │  Lint   │──►│  SAST   │──►│  SCA    │──►│  Build  │ │
│  │ (Swift) │   │(SwiftLint)│  │(OWASP)  │   │         │ │
│  └─────────┘   └─────────┘   └─────────┘   └─────────┘ │
│       │             │             │             │        │
│       ▼             ▼             ▼             ▼        │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐ │
│  │ Report  │   │ Report  │   │ Report  │   │  Sign   │ │
│  └─────────┘   └─────────┘   └─────────┘   └─────────┘ │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### Пороговые значения

| Метрика | Порог | Действие |
|:---|:---|:---|
| **Critical CVE** | 0 | Блокировка пайплайна |
| **High CVE** | < 3 | Предупреждение |
| **Medium CVE** | < 10 | Рекомендация |
| **Low CVE** | Не ограничено | Информирование |
| **SAST Errors** | 0 | Блокировка пайплайна |
| **SAST Warnings** | < 20 | Предупреждение |

---

## Практическая реализация

### 1. SAST: Статический анализ (iOS)

**SwiftLint:**
```yaml
swiftlint:
  runs-on: macos-14
  steps:
    - uses: actions/checkout@v4
    
    - name: Run SwiftLint
      run: |
        swiftlint lint \
          --reporter json \
          --output swiftlint-report.json \
          --strict
        
    - name: Check for Errors
      run: |
        ERRORS=$(jq '.[] | select(.severity == "error") | length' swiftlint-report.json)
        if [ "$ERRORS" -gt 0 ]; then
          echo "Found $ERRORS SwiftLint errors"
          exit 1
        fi
```

### 2. SAST: Статический анализ (Android)

**Detekt:**
```groovy
// app/build.gradle
plugins {
    id 'io.gitlab.arturbosch.detekt'
}

detekt {
    input.setFrom("src/main/java", "src/main/kotlin")
    config.setFrom("config/detekt/detekt.yml")
    buildUponDefaultConfig = true
    allRules = false
    
    reports {
        html.required.set(true)
        sarif.required.set(true)
    }
}
```

**Android Lint (встроенный):**
```groovy
// app/build.gradle
android {
    lintOptions {
        abortOnError true
        xmlReport true
        htmlReport true
        baseline "lint-baseline.xml"
    }
}
```

### 3. SCA: Проверка зависимостей (iOS)

**OWASP Dependency-Check:**
```yaml
dependency_check:
  runs-on: macos-14
  steps:
    - uses: actions/checkout@v4
    
    - name: Run OWASP Dependency Check
      run: |
        dependency-check \
          --project "MyApp" \
          --scan . \
          --format HTML \
          --format JSON \
          --out dependency-check-report \
          --failOnCVSS 7
    
    - name: Upload Report
      uses: actions/upload-artifact@v4
      with:
        name: dependency-check-report
        path: dependency-check-report/
```

### 4. SCA: Проверка зависимостей (Android)

**Gradle Dependency Check:**
```groovy
// app/build.gradle
plugins {
    id 'org.owasp.dependencycheck'
}

dependencyCheck {
    failBuildOnCVSS = 7
    suppressionFile = 'dependency-check-suppressions.xml'
    
    formats = ['HTML', 'JSON', 'SARIF']
    outputDirectory = "${buildDir}/reports/dependency-check"
}
```

### 5. DAST: MobSF для Android

```yaml
mobsf:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    
    - name: Setup MobSF
      run: |
        docker pull mobsf/mobsf-android:latest
    
    - name: Run MobSF Scan
      run: |
        docker run \
          -v $PWD:/tmp/mobsf \
          mobsf/mobsf-android:latest \
          /tmp/mobsf/app-release.apk \
          /tmp/mobsf/mobsf-report
    
    - name: Upload Report
      uses: actions/upload-artifact@v4
      with:
        name: mobsf-report
        path: mobsf-report/
```

### 6. DAST: Frida для iOS (Dynamic Analysis)

```bash
# Установка Frida
pip install frida-tools

# Мониторинг API вызовов
frida -U -f com.company.app -l ios_monitor.js --no-pause

# Проверка Keychain доступа
frida -U -f com.company.app -l keychain_check.js --no-pause
```

**Пример Frida-скрипта для проверки Keychain:**
```javascript
// keychain_check.js
ObjC.Block.implement({
  '- (void) SecItemAdd:(id)query': function(self, sel, query) {
    console.log('Keychain Add:', query);
    return this.original(self, sel, query);
  }
});
```

---

## Дополнительная информация

### Best Practices

1. **Shift Left:** Запускайте security scanning на каждом PR, а не только в main.
2. **Fail on Critical:** Блокируйте пайплайн при обнаружении critical CVE.
3. **Regular Updates:** Обновляйте зависимости еженедельно.
4. **Suppression:** Используйте suppression files для ложных срабатываний.
5. **Monitoring:** Отслеживайте новые CVE для ваших зависимостей.

### Compliance Requirements

| Стандарт | Требование | Инструмент |
|:---|:---|:---|
| **OWASP MASVS** | Security Testing | SAST + DAST |
| **PCI DSS** | Vulnerability Scanning | SCA + SAST |
| **GDPR** | Data Protection | SAST + Secrets |
| **SOC 2** | Security Controls | SAST + SCA |

### Интеграция с IDE

**Xcode (iOS):**
```bash
# Установка SwiftLint через CocoaPods
pod 'SwiftLint'

# Запуск в Xcode
swiftlint lint --config .swiftlint.yml
```

**Android Studio:**
```groovy
// build.gradle
plugins {
    id 'com.android.plugin'
    id 'org.jetbrains.kotlin.android'
    id 'org.owasp.dependencycheck'
}
```

### См. также:
*   **[SAST Overview](../DevSecOps/sast_overview.md)** — общие концепции SAST
*   **[DAST Overview](../DevSecOps/dast_overview.md)** — общие концепции DAST
*   **[SAST/DAST CI/CD Integration](../DevSecOps/sast_dast_cicd_integration.md)** — интеграция в CI/CD
*   **[Secrets Management](../DevSecOps/secrets_management.md)** — управление секретами
*   **[DevSecOps Overview](../DevSecOps/devsecops_overview.md)** — обзор методологии
*   **[Mobile CI/CD Overview](./index.md)**
*   **[Feature Flags](./feature-flags-mobile.md)**
*   **[Incident Response](./incident-response-mobile.md)**
*   **[Disaster Recovery](./disaster-recovery-mobile-ci.md)**
