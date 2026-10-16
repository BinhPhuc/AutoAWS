import { Navigate } from 'react-router-dom'
import { useConnections } from '@/hooks/useConnections'
import { PageLoading } from '@/components/layout/PageState'

/** "/" → /chat when a verified connection exists, otherwise /connect. */
export function HomeRedirect() {
  const { data, isPending, isError } = useConnections()
  if (isPending) return <PageLoading />
  const hasConnected = !isError && (data ?? []).some((c) => c.status === 'connected')
  return <Navigate to={hasConnected ? '/chat' : '/connect'} replace />
}
