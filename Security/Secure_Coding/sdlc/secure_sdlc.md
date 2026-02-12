# Secure SDLC (SSDLC)

## Определение

**Secure SDLC (SSDLC)** — это расширение SDLC с интеграцией практик безопасности на каждом этапе разработки, начиная с самых ранних фаз.

## Интеграция безопасности в SDLC

```
TRADITIONAL SDLC:                    SECURE SDLC:

Planning                              Planning
  │                                     │
  ▼                                     ▼
Requirements ─────►                  Threat Modeling
  │                                     │
  ▼                                     ▼
Design                                 Secure Design
  │                                     │
  ▼                                     ▼
Development ◄───── Security bugs      Secure Coding
  │                                     │
  ▼                                     ▼
Testing ◄───────── Security testing   SAST/DAST/Pentest
  │                                     │
  ▼                                     ▼
Deployment ◄────── Last minute scan   Secure Deployment
  │                                     │
  ▼                                     ▼
Maintenance ◄───── Emergency patches  Security Monitoring
```

## Этапы Secure SDLC

### 1. Planning — Threat Modeling

**STRIDE модель:**
- **S**poofing — подмена идентичности
- **T**ampering — модификация данных
- **R**epudiation — отказ от действий
- **I**nformation Disclosure — утечка информации
- **D**enial of Service — отказ в обслуживании
- **E**levation of Privilege — повышение привилегий

**Инструменты:**
- Microsoft Threat Modeling Tool
- OWASP Threat Dragon
- IriusRisk

### 2. Design — Secure Architecture

**Principles:**
- Defense in depth
- Least privilege
- Fail securely
- Separation of duties
- Security by default

**Артефакты:**
- Security architecture diagrams
- Trust boundaries
- Data flow diagrams (DFD)

### 3. Development — Secure Coding

**Практики:**
- OWASP Top 10 awareness
- Secure coding standards
- Code reviews с security focus
- Linting (security rules)

**Обучение:**
- Secure Code Warrior
- HackEDU
- OWASP WebGoat

### 4. Testing — Security Testing

**Типы тестирования:**

| Тип | Когда | Инструменты |
|-----|-------|-------------|
| **SAST** | Во время разработки | SonarQube, Checkmarx, Semgrep |
| **DAST** | На работающем приложении | OWASP ZAP, Burp Suite |
| **IAST** | В runtime | Contrast Security, Seeker |
| **SCA** | Анализ зависимостей | Snyk, OWASP Dependency-Check |
| **Penetration Testing** | Перед релизом | Ручное тестирование |
| **Fuzzing** | Автоматизированное | AFL, libFuzzer |

### 5. Deployment — Secure DevOps (DevSecOps)

**Security Gates в CI/CD:**

```yaml
# .gitlab-ci.yml пример
stages:
  - build
  - test
  - security
  - deploy

sast:
  stage: security
  image: returntocorp/semgrep
  script:
    - semgrep --config=auto .
  allow_failure: false  # Блокировать merge при ошибках

dependency_scan:
  stage: security
  image: snyk/snyk
  script:
    - snyk test --severity-threshold=high
  allow_failure: true   # Предупреждение, но не блокировка

container_scan:
  stage: security
  image: aquasec/trivy
  script:
    - trivy image $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
```

### 6. Operations — Security Monitoring

**Мониторинг:**
- SIEM (Splunk, ELK, QRadar)
- WAF logs
- Intrusion Detection
- Vulnerability management

## Безопасность в DevSecOps

```
┌─────────────────────────────────────────────────────────────┐
│                    DEVSECOPS PIPELINE                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  PLAN              THREAT MODELING                          │
│   │                    │ (STRIDE, DFD)                      │
│   ▼                    ▼                                    │
│  CODE ───────────► SECURE CODING                            │
│   │                    │ (OWASP, standards)                 │
│   ▼                    ▼                                    │
│  BUILD ──────────► SAST/SCA/LINT                            │
│   │                    │ (SonarQube, Snyk)                  │
│   ▼                    ▼                                    │
│  TEST ───────────► DAST/FUZZING                             │
│   │                    │ (ZAP, custom tests)                │
│   ▼                    ▼                                    │
│  RELEASE ────────► IMAGE SCANNING                           │
│   │                    │ (Trivy, Clair)                     │
│   ▼                    ▼                                    │
│  DEPLOY ─────────► IaC SCANNING                             │
│   │                    │ (Checkov, tfsec)                   │
│   ▼                    ▼                                    │
│  OPERATE ────────► RUNTIME PROTECTION                       │
│   │                    │ (RASP, monitoring)                 │
│   ▼                    ▼                                    │
│  MONITOR ────────► SIEM/LOGGING                             │
│                      (Splunk, ELK)                          │
└─────────────────────────────────────────────────────────────┘
```
