import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/api/client'
import type { LlmConfig } from '@/api/types'
import { S } from '@/lib/strings'
import { AdminPage } from './AdminPage'

const { admin, auth } = vi.hoisted(() => ({
  admin: { getLlm: vi.fn(), saveLlm: vi.fn(), resetLlm: vi.fn(), testLlm: vi.fn() },
  auth: { me: vi.fn(), config: vi.fn() },
}))
vi.mock('@/api/admin', () => ({ adminApi: admin }))
vi.mock('@/api/auth', () => ({ authApi: auth }))

const NO_KEY = { set: false, hint: null, updated_at: null }
const env: LlmConfig = {
  provider: 'bedrock',
  source: 'env',
  storage: 'secretsmanager',
  updated_at: null,
  updated_by: null,
  bedrock: {
    model: 'anthropic.claude-opus-5-5',
    fallback_model: '',
    region: 'ap-southeast-2',
    auth: 'api_key',
    access_key_id: '',
    role_arn: '',
    external_id: '',
    secrets: { api_key: NO_KEY, secret_access_key: NO_KEY },
  },
  anthropic: { model: 'claude-opus-5-5', base_url: '', secrets: { api_key: NO_KEY } },
  openai: { model: '', base_url: 'http://localhost:11434/v1', secrets: { api_key: NO_KEY } },
}
const KEY = 'ABSKexample-bedrock-api-key-1234'
const t = S.admin

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <AdminPage />
    </QueryClientProvider>,
  )
}

describe('AdminPage', () => {
  afterEach(cleanup)
  beforeEach(() => {
    vi.clearAllMocks()
    auth.me.mockResolvedValue({
      data: { user_id: 'local', username: 'local', auth_mode: 'none', is_admin: true },
      message: 'OK',
    })
    admin.getLlm.mockResolvedValue({ data: env, message: 'OK' })
  })

  it('is closed to users who are not admins', async () => {
    auth.me.mockResolvedValue({
      data: { user_id: 'u', username: 'u', auth_mode: 'cognito', is_admin: false },
      message: 'OK',
    })
    renderPage()
    expect(await screen.findByText(t.onlyAdmins)).toBeInTheDocument()
    expect(admin.getLlm).not.toHaveBeenCalled()
  })

  it('saves a Bedrock API key without ever showing it again', async () => {
    const user = userEvent.setup()
    const saved: LlmConfig = {
      ...env,
      source: 'admin',
      updated_at: '2026-11-13T10:00:00Z',
      updated_by: 'local',
      bedrock: {
        ...env.bedrock,
        secrets: {
          api_key: { set: true, hint: '…1234', updated_at: '2026-11-13T10:00:00Z' },
          secret_access_key: NO_KEY,
        },
      },
    }
    admin.saveLlm.mockResolvedValue({ data: saved, message: 'LLM settings saved' })
    renderPage()
    const keyInput = await screen.findByLabelText(t.bedrockApiKey)
    expect(keyInput).toHaveAttribute('type', 'password')
    expect(screen.getByText(t.secretNotSet)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: t.save })).toBeDisabled()
    await user.type(keyInput, KEY)
    expect(screen.getByRole('button', { name: t.test })).toBeDisabled() // unsaved changes
    await user.click(screen.getByRole('button', { name: t.save }))
    await waitFor(() =>
      expect(admin.saveLlm).toHaveBeenCalledWith({
        provider: 'bedrock',
        bedrock: {
          model: 'anthropic.claude-opus-5-5',
          fallback_model: '',
          region: 'ap-southeast-2',
          auth: 'api_key',
          access_key_id: '',
          role_arn: '',
          external_id: '',
        },
        anthropic: { model: 'claude-opus-5-5', base_url: '' },
        openai: { model: '', base_url: 'http://localhost:11434/v1' },
        secrets: { 'bedrock.api_key': KEY },
      }),
    )
    // the form restarts from the saved copy: the field is empty, only the hint remains
    expect(await screen.findByText(/Set …1234/)).toBeInTheDocument()
    expect(screen.getByLabelText(t.bedrockApiKey)).toHaveValue('')
    expect(document.body.textContent).not.toContain(KEY)
  })

  it('removes a stored key', async () => {
    const user = userEvent.setup()
    admin.getLlm.mockResolvedValue({
      data: {
        ...env,
        source: 'admin',
        updated_at: '2026-11-13T10:00:00Z',
        bedrock: {
          ...env.bedrock,
          auth: 'iam',
          secrets: {
            ...env.bedrock.secrets,
            api_key: { set: true, hint: '…1234', updated_at: null },
          },
        },
      },
      message: 'OK',
    })
    admin.saveLlm.mockResolvedValue({ data: env, message: 'LLM settings saved' })
    renderPage()
    // iam auth hides the key field; switch the auth back to api_key to see / remove it
    await screen.findByText(t.authHints.iam)
    await user.click(screen.getByLabelText(t.auth))
    await user.click(await screen.findByRole('option', { name: t.auths.api_key }))
    await user.click(screen.getByRole('button', { name: t.secretRemove }))
    expect(screen.getByText(t.secretWillRemove)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: t.save }))
    await waitFor(() =>
      expect(admin.saveLlm.mock.calls[0][0].secrets).toEqual({ 'bedrock.api_key': null }),
    )
  })

  it('shows why the server refused the settings', async () => {
    const user = userEvent.setup()
    admin.saveLlm.mockRejectedValue(
      new ApiError({
        status_code: 422,
        error: 'VALIDATION_ERROR',
        message: 'Invalid request: bedrock auth api_key needs a Bedrock API key',
        path: '/api/admin/llm',
        timestamp: '',
      }),
    )
    renderPage()
    const model = await screen.findByLabelText(t.model)
    await user.clear(model)
    await user.type(model, 'anthropic.claude-sonnet-5-5')
    await user.click(screen.getByRole('button', { name: t.save }))
    expect(await screen.findByRole('alert')).toHaveTextContent('needs a Bedrock API key')
  })

  it('tests the saved provider', async () => {
    const user = userEvent.setup()
    admin.testLlm.mockResolvedValue({
      data: {
        ok: false,
        provider: 'bedrock',
        model: 'anthropic.claude-opus-5-5',
        latency_ms: null,
        reply: null,
        error: 'bedrock: no access to model',
      },
      message: 'OK',
    })
    renderPage()
    await user.click(await screen.findByRole('button', { name: t.test }))
    expect(await screen.findByRole('status')).toHaveTextContent(
      `${t.testFailed}: bedrock: no access to model`,
    )
  })

  it('switches the provider and shows only its settings', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByLabelText(t.bedrockApiKey)
    await user.click(screen.getByLabelText(t.provider))
    await user.click(await screen.findByRole('option', { name: t.providers.openai }))
    expect(screen.getByLabelText(t.openaiKey)).toBeInTheDocument()
    expect(screen.queryByLabelText(t.bedrockApiKey)).not.toBeInTheDocument()
    expect(screen.getByLabelText(t.baseUrl)).toHaveValue('http://localhost:11434/v1')
  })
})
