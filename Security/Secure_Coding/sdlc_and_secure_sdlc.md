# SDLC и Secure SDLC

## Определения

**SDLC (Software Development Life Cycle)** — это процесс разработки программного обеспечения, описывающий этапы создания, тестирования, развертывания и поддержки приложений.

**Secure SDLC (SSDLC)** — это расширение SDLC с интеграцией практик безопасности на каждом этапе разработки, начиная с самых ранних фаз.

## SDLC (Software Development Life Cycle)

### Модели SDLC

#### 1. Waterfall (Каскадная модель)

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  Требова- │───►│ Проекти- │───►│ Разработ-│───►│ Тестиро- │───►│  Внедре- │
│   ния     │    │ рование  │    │    ка    │    │  вание   │    │   ние    │
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
     │                │                │                │                │
   Анализ          Дизайн          Кодирование      QA/Testing      Production
   спецификаций    архитектуры                       Bug fixes
```

**Характеристики:**
- Последовательные этапы
- Полное документирование перед переходом
- Жесткие сроки и бюджеты
- Сложно вносить изменения

**Когда использовать:**
- Проекты с четкими требованиями
- Регулируемые отрасли (фарма, авиация)
- Малые проекты

#### 2. Agile (Гибкая методология)

```
┌─────────────────────────────────────────────────────────────┐
│                    ПОВТОРЯЮЩИЙСЯ ЦИКЛ                       │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐     │
│  │Планирова│──►│Разработка│──►│Тестирова│──►│Обзор/   │     │
│  │  ние    │   │         │   │  ние    │   │Демо     │─────┤
│  └─────────┘   └─────────┘   └─────────┘   └─────────┘     │
│                                                   │         │
│  ┌────────────────────────────────────────────────┘         │
│  │  Ретроспектива                                          │
│  └────────────────────────────────────────────────────────►
│  
  Sprint 1-4 недели
```

**Характеристики:**
- Итеративный подход
- Гибкость изменений
- Постоянная обратная связь
- Кросс-функциональные команды

**Фреймворки:**
- Scrum
- Kanban
- Extreme Programming (XP)

#### 3. DevOps

```
┌─────────────────────────────────────────────────────────────┐
│                      CI/CD PIPELINE                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  DEV ──────► BUILD ──────► TEST ──────► DEPLOY ──────► OPS │
│   │            │            │            │           │     │
│   │            │            │            │           │     │
│   └────────────┴────────────┴────────────┴───────────┘     │
│              Continuous Integration/Delivery               │
│                                                            │
│  Plan ──► Code ──► Build ──► Test ──► Release ──► Deploy ─► Operate ──► Monitor
│  └──────────────────────────────────────────────────────────────────────┘
│                              Feedback Loop
```

**Principles (CALMS):**
- **C**ulture — культура сотрудничества
- **A**utomation — автоматизация процессов
- **L**ean — бережливое производство
- **M**easurement — измерение метрик
- **S**haring — обмен знаниями

### Этапы SDLC

| Этап | Деятельность | Артефакты |
|------|--------------|-----------|
| **1. Planning** | Анализ требований, Feasibility study | SRS (Software Requirements Specification), roadmap |
| **2. Design** | Архитектура, UI/UX design | Design docs, wireframes, ER diagrams |
| **3. Development** | Кодирование, unit tests | Source code, documentation |
| **4. Testing** | QA, integration testing | Test cases, bug reports |
| **5. Deployment** | Release, installation | Deployment scripts, runbooks |
| **6. Maintenance** | Bug fixes, updates | Patch notes, incident reports |

## Secure SDLC (SSDLC)

### Интеграция безопасности в SDLC

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

### Этапы Secure SDLC

#### 1. Planning — Threat Modeling

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

#### 2. Design — Secure Architecture

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

#### 3. Development — Secure Coding

**Практики:**
- OWASP Top 10 awareness
- Secure coding standards
- Code reviews с security focus
- Linting (security rules)

**Обучение:**
- Secure Code Warrior
- HackEDU
- OWASP WebGoat

#### 4. Testing — Security Testing

**Типы тестирования:**

| Тип | Когда | Инструменты |
|-----|-------|-------------|
| **SAST** | Во время разработки | SonarQube, Checkmarx, Semgrep |
| **DAST** | На работающем приложении | OWASP ZAP, Burp Suite |
| **IAST** | В runtime | Contrast Security, Seeker |
| **SCA** | Анализ зависимостей | Snyk, OWASP Dependency-Check |
| **Penetration Testing** | Перед релизом | Ручное тестирование |
| **Fuzzing** | Автоматизированное | AFL, libFuzzer |

#### 5. Deployment — Secure DevOps (DevSecOps)

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

#### 6. Operations — Security Monitoring

**Мониторинг:**
- SIEM (Splunk, ELK, QRadar)
- WAF logs
- Intrusion Detection
- Vulnerability management

### Безопасность в DevSecOps

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

### Maturity Models

**BSIMM (Building Security In Maturity Model):**
- Оценка зрелости безопасности
- 4 уровня: начальный, управляемый, определенный, оптимизирующий

**OWASP SAMM (Software Assurance Maturity Model):**
- Governance
- Design
- Implementation
- Verification
- Operations

### Метрики Secure SDLC

| Метрика | Цель | Как измерять |
|---------|------|--------------|
| **Defect density** | < 0.1 defects/LOC | Баги / строки кода |
| **Time to fix** | Критические: < 24h | MTTR для security багов |
| **False positive rate** | < 20% | FP / (TP + FP) |
| **Security test coverage** | > 80% | Security tests / Total tests |
| **Vulnerability escape rate** | 0 critical in prod | Баги найденные в production |
| **Mean time to patch** | < 7 days для critical | Время от disclosure до patch |

## Практические сценарии

### Сценарий 1: Внедрение SAST в CI/CD

```yaml
# GitHub Actions workflow
name: Security Scan

on: [push, pull_request]

jobs:
  security:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    
    - name: Run Semgrep
      uses: returntocorp/semgrep-action@v1
      with:
        config: >-
          p/security-audit
          p/owasp-top-ten
          p/cwe-top-25
    
    - name: Dependency Check
      uses: snyk/actions/node@master
      env:
        SNYK_TOKEN: ${{ secrets.SNYK_TOKEN }}
    
    - name: Upload results
      uses: github/codeql-action/upload-sarif@v2
      if: always()
      with:
        sarif_file: semgrep-results.sarif
```

### Сценарий 2: Threat Modeling с STRIDE

```
Пример: Веб-приложение для онлайн-банкинга

Data Flow Diagram:
┌────────┐      ┌──────────┐      ┌──────────┐      ┌────────┐
│ User   │──────►│   WAF    │──────►│ Web App  │──────►│Database│
└────────┘      └──────────┘      └──────────┘      └────────┘
                       │                 │
                       │            ┌────▼────┐
                       │            │  API    │
                       │            └────┬────┘
                       │                 │
                  ┌────▼────┐      ┌────▼────┐
                  │  Logs   │      │ Payment │
                  └─────────┘      └─────────┘

STRIDE Analysis:
1. User → WAF: Spoofing (fake user), Tampering (modify request)
2. WAF → Web App: Denial of Service (bypass WAF)
3. Web App → Database: Information Disclosure (SQL injection)
4. Web App → Payment: Repudiation (no audit logs)
5. Internal → Logs: Elevation of Privilege (admin access)
```

### Сценарий 3: Security Champions Program

```
Структура:
├── Security Team (централизованная функция)
│   ├── Security Architecture
│   ├── AppSec Engineers
│   └── Security Operations
│
└── Security Champions (в каждой команде разработки)
    ├── Dev Team A: Champion John
    ├── Dev Team B: Champion Jane
    └── Dev Team C: Champion Bob

Обязанности Security Champion:
- 20% времени на security
- Review security issues
- Обучение команды
- Связь с Security Team
- Участие в threat modeling
```

## Дополнительная информация

- [OWASP SAMM](https://owasp.org/www-project-samm/)
- [BSIMM](https://www.bsimm.com/)
- [Microsoft SDL](https://www.microsoft.com/en-us/securityengineering/sdl)
- [NIST SSDF](https://csrc.nist.gov/projects/ssdf)
- [OWASP DevSecOps Guideline](https://owasp.org/www-project-devsecops-guideline/)
