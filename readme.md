# Yuno Backend - AI-Powered Chat Widget System

## 🎯 Overview

Yuno is a secure, scalable backend system for an AI-powered chat widget that can be embedded on any website. It provides intelligent customer support through OpenAI's GPT models, with features like semantic search (RAG), lead capture, analytics tracking, and multi-tier rate limiting.

### Key Features
- 🔐 **JWT-based Authentication** - Secure widget authentication with domain validation
- 🤖 **AI-Powered Chat** - Uses OpenAI GPT-4 for intelligent responses
- 🔍 **Semantic Search (RAG)** - Vector-based search for contextual answers
- 📊 **Lead Capture** - Automatic extraction and storage of customer information
- ⚡ **Rate Limiting** - Multi-tier limits based on subscription plans
- 📈 **Analytics** - Mixpanel integration for usage tracking
- 🌐 **Multi-domain Support** - One backend serving multiple client websites

## 🏗️ Architecture

```
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│                 │         │                 │         │                 │
│  Client Website │ <-----> │   Yuno Backend  │ <-----> │    Supabase     │
│   (yuno.js)     │  JWT    │  (Flask + Redis)│         │   (PostgreSQL)  │
│                 │         │                 │         │                 │
└─────────────────┘         └─────────────────┘         └─────────────────┘
                                     │                           │
                                     v                           v
                            ┌─────────────────┐         ┌─────────────────┐
                            │                 │         │                 │
                            │     OpenAI      │         │  Vector Search  │
                            │   (GPT-4-mini)  │         │   (Embeddings)  │
                            │                 │         │                 │
                            └─────────────────┘         └─────────────────┘
```

## 📁 Project Structure

```
yuno-backend/
├── app.py                 # Main Flask application entry point
├── requirements.txt       # Python dependencies
├── .env.example          # Environment variables template
│
├── routes/               # API endpoint handlers
│   ├── __init__.py
│   ├── auth.py          # Widget authentication endpoints
│   └── chat.py          # Chat conversation endpoints
│
├── services/            # Business logic and external integrations
│   ├── __init__.py
│   ├── jwt_service.py       # JWT token generation/validation
│   ├── domain_service.py    # Domain validation and ownership
│   └── rate_limit_service.py # Redis-based rate limiting
│
├── models/              # Data models and database interactions
│   ├── __init__.py
│   └── site.py          # Site/customer data model
│
├── utils/               # Helper functions and utilities
│   ├── __init__.py
│   └── helpers.py       # Security, validation, and formatting helpers
│
└── yuno.js             # Client-side widget (deployed separately)
```

## 🔄 Request Flow

### 1. Widget Initialization
```
Client Website                    Yuno Backend
     │                                │
     ├─[1]─> Load yuno.js            │
     │                                │
     ├─[2]─> POST /widget/authenticate│
     │       {site_id, domain, nonce} │
     │                                │
     │<──[3]── JWT Token ────────────┤
     │                                │
     └─[4]─> Store token locally      │
```

### 2. Chat Conversation
```
Widget (yuno.js)                  Yuno Backend                    Services
     │                                │                               │
     ├─[1]─> POST /ask               │                               │
     │       {messages, token}        │                               │
     │                                ├─[2]─> Verify JWT              │
     │                                ├─[3]─> Check Rate Limits       │
     │                                ├─[4]─> Rewrite Query           │
     │                                ├─[5]─> Generate Embedding      │
     │                                ├─[6]─> Semantic Search         │
     │                                ├─[7]─> Call OpenAI            │
     │                                ├─[8]─> Extract Leads          │
     │                                ├─[9]─> Store Analytics        │
     │<──[10]─ AI Response ──────────┤                               │
```

## 📋 File Descriptions

### Core Application

#### `app.py`
- Flask application initialization
- CORS configuration for cross-origin requests
- Blueprint registration (auth, chat)
- Global error handlers (401, 403, 429, 500)
- Health check endpoint
- Sentry integration for error tracking

### Routes

#### `routes/auth.py`
Handles widget authentication and security:
- `POST /widget/authenticate` - Issues JWT tokens after validating site_id and domain
- `POST /widget/verify` - Validates existing JWT tokens
- `POST /widget/refresh` - Refreshes expiring tokens
- Checks: domain ownership, plan status, widget enabled state

#### `routes/chat.py`
Manages AI chat conversations:
- `POST /ask` - Main chat endpoint (JWT required)
- Query rewriting for context-aware responses
- OpenAI embedding generation
- Semantic search through Supabase
- GPT-4 response generation
- Lead capture detection
- Analytics tracking via Mixpanel
- Comprehensive error handling

### Services

#### `services/jwt_service.py`
JWT token management:
- Token generation with expiry
- Token verification with audience/issuer validation
- Token refresh functionality
- Payload extraction utilities

#### `services/domain_service.py`
Domain validation and security:
- Domain cleaning and normalization
- Subdomain support validation
- Domain ownership verification
- CORS origin validation
- URL parsing utilities

#### `services/rate_limit_service.py`
Redis-based rate limiting:
- Multi-window limits (minute/hour/day)
- Plan-based configurations (free/basic/pro/enterprise)
- Usage tracking and statistics
- TTL-based automatic cleanup

### Models

#### `models/site.py`
Supabase database interactions:
- Site CRUD operations
- Plan management
- Usage statistics
- Widget toggle functionality
- Rate limit configurations by plan

### Utilities

#### `utils/helpers.py`
Reusable helper functions organized by category:
- **SecurityHelpers**: Site ID generation, token creation, hashing
- **ValidationHelpers**: Email, domain, URL validation
- **DateTimeHelpers**: Timestamp handling, expiry checks
- **ResponseHelpers**: Standardized API responses
- **LoggingHelpers**: Security event logging
- **ConfigHelpers**: Plan configurations
- **DataHelpers**: Domain cleaning, data masking

### Client Widget

#### `yuno.js`
Self-contained chat widget:
- Web Component implementation
- JWT authentication flow
- Themeable UI (dark/light/blue/green)
- Auto-retry on token expiry
- Local session management
- Typing indicators
- Lead capture UI

## 🔐 Security Features

1. **Authentication**
   - JWT tokens with 1-hour expiry
   - Domain ownership validation
   - Nonce-based request uniqueness

2. **Rate Limiting**
   - Per-minute: 30-300 requests
   - Per-hour: 200-2500 requests  
   - Per-day: 500-15000 requests
   - Based on subscription tier

3. **Input Validation**
   - Domain format validation
   - Email validation
   - Input sanitization
   - SQL injection protection (via Supabase)

4. **Domain Security**
   - Strict domain matching
   - Subdomain support (configurable)
   - CORS origin validation

## 🗄️ Database Schema (Supabase)

### Sites Table
```sql
sites {
  id: uuid
  site_id: string (unique, 16 chars)
  domain: string
  user_id: string
  plan_type: enum (free, basic, pro, enterprise)
  plan_active: boolean
  widget_enabled: boolean
  created_at: timestamp
  theme: string
  custom_config: jsonb
}
```

### Chat History Table
```sql
chat_history {
  id: uuid
  site_id: string
  session_id: string
  user_id: string
  page_url: string
  role: string (user, assistant)
  content: text
  timestamp: timestamp
  raw_json_output: jsonb
  lang: string
  answer_confidence: float
  intent: string
  tokens_used: integer
  user_sentiment: string
  compliance_red_flag: boolean
}
```

### Leads Table
```sql
leads {
  id: uuid
  site_id: string
  session_id: string
  name: string
  email: string
  phone: string
  message: text
  intent: text
  created_at: timestamp
}
```

## 🚀 Deployment

### Environment Variables
```bash
# Supabase
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=your-supabase-anon-key

# OpenAI
OPENAI_API_KEY=sk-...

# Security
JWT_SECRET=your-secret-key

# Redis
REDIS_URL=redis://localhost:6379

# Monitoring (Optional)
SENTRY_DSN=https://xxx@sentry.io/xxx
MIXPANEL_TOKEN=your-mixpanel-token
```

### Running Locally
```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
cp .env.example .env
# Edit .env with your values

# Run development server
python app.py

# Or production server
gunicorn app:app --workers 4
```

### Production Deployment (Render/Heroku)
1. Set all environment variables
2. Ensure Redis addon is configured
3. Deploy with `gunicorn app:app`

## 🔧 Configuration

### Widget Installation (Client-side)
```html
<script 
  src="https://cdn.helloyuno.com/yuno.js"
  site_id="YOUR_SITE_ID"
  theme="dark"
  position="bottom-right"
  primary_color="#FF6B35"
  welcome_message="Hi! How can I help you today?"
></script>
```

### Plan Limits
| Plan       | Per Minute | Per Hour | Per Day | Monthly |
|------------|------------|----------|---------|---------|
| Free       | 30         | 200      | 500     | 1,000   |
| Basic      | 60         | 500      | 2,000   | 10,000  |
| Pro        | 120        | 1,000    | 5,000   | 50,000  |
| Enterprise | 300        | 2,500    | 15,000  | 200,000 |

## 🧪 Testing

### Test Authentication
```bash
curl -X POST https://api.helloyuno.com/widget/authenticate \
  -H "Content-Type: application/json" \
  -d '{
    "site_id": "test123",
    "domain": "example.com",
    "nonce": "random-nonce"
  }'
```

### Test Chat
```bash
curl -X POST https://api.helloyuno.com/ask \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -d '{
    "messages": [{"role": "user", "content": "Hello"}],
    "page_url": "https://example.com",
    "session_id": "test-session"
  }'
```

## 📊 Monitoring

- **Sentry**: Error tracking and performance monitoring
- **Mixpanel**: User analytics and conversation tracking
- **Redis**: Rate limit statistics
- **Supabase**: Database metrics and logs

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Follow existing code patterns
4. Add tests for new features
5. Submit a pull request

## 📄 License

[Your License Here]

## 🆘 Support

For issues or questions:
- GitHub Issues: [your-repo-url]/issues
- Email: support@helloyuno.com
- Documentation: [your-docs-url]

---

Built with ❤️ by the Yuno team