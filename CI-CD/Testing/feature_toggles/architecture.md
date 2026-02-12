# Архитектура Feature Toggles

## Компоненты системы

```
┌─────────────────────────────────────────────────────────────┐
│                    APPLICATION                              │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │   Feature   │  │   Feature   │  │   Feature   │         │
│  │   Toggle    │  │   Toggle    │  │   Toggle    │         │
│  │   Check     │  │   Check     │  │   Check     │         │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
│         │                │                │                │
│         └────────────────┼────────────────┘                │
│                          │                                 │
│                   ┌──────▼──────┐                         │
│                   │   Feature   │                         │
│                   │   Toggle    │                         │
│                   │   Client    │                         │
│                   │   (SDK)     │                         │
│                   └──────┬──────┘                         │
└──────────────────────────┼─────────────────────────────────┘
                           │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
┌────────▼────────┐ ┌──────▼──────┐ ┌───────▼────────┐
│   Config File   │ │   Database  │ │   External     │
│   (YAML/JSON)   │ │   (Postgres)│ │   Service      │
│                 │ │   MongoDB)  │ │   (LaunchDarkly│
│                 │ │             │ │   Unleash)     │
└─────────────────┘ └─────────────┘ └────────────────┘
```

## Хранение состояния toggles

### 1. Файлы конфигурации (для простых случаев):

```yaml
# features.yaml
features:
  new-checkout:
    enabled: true
    
  dark-mode:
    enabled: false
    users:
      - admin@example.com
      
  beta-feature:
    enabled: true
    percentage: 10  # 10% пользователей
```

### 2. База данных (для динамических изменений):

```sql
CREATE TABLE feature_flags (
    name VARCHAR(255) PRIMARY KEY,
    enabled BOOLEAN DEFAULT false,
    strategy VARCHAR(50), -- 'default', 'userId', 'percentage'
    parameters JSONB,     -- {'userIds': [], 'percentage': 10}
    updated_at TIMESTAMP
);
```

### 3. Специализированные сервисы:

- **LaunchDarkly** — SaaS-решение
- **Unleash** — Open-source self-hosted
- **Split.io** — Enterprise feature management
- **Flagsmith** — Open-source
