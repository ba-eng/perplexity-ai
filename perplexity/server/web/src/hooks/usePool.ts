import { useState, useEffect, useCallback } from 'react'
import { fetchPoolStatus, fetchHeartbeatConfig, fetchFallbackConfig, PoolStatus, HeartbeatConfig, FallbackConfig } from 'lib/api'

export function usePool() {
  const [data, setData] = useState<PoolStatus>({
    total: 0,
    available: 0,
    mode: '-',
    clients: [],
  })
  const [hbConfig, setHbConfig] = useState<HeartbeatConfig | null>(null)
  const [fallbackConfig, setFallbackConfig] = useState<FallbackConfig>({ fallback_to_auto: true })
  const [isLoading, setIsLoading] = useState(false)
  const [lastSync, setLastSync] = useState<string | null>(null)

  const refreshData = useCallback(async () => {
    setIsLoading(true)
    try {
      const [poolData, hbResp, fallbackResp] = await Promise.all([
        fetchPoolStatus(),
        fetchHeartbeatConfig(),
        fetchFallbackConfig(),
      ])
      setData(poolData)
      setLastSync(new Date().toLocaleTimeString('en-US', { hour12: false }))

      if (hbResp.status === 'ok' && hbResp.config) {
        setHbConfig(hbResp.config)
      }
      if (fallbackResp.status === 'ok' && fallbackResp.config) {
        setFallbackConfig(fallbackResp.config)
      }
    } catch (e) {
      console.error('Failed to fetch data:', e)
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    refreshData()
    const interval = setInterval(refreshData, 30000)
    return () => clearInterval(interval)
  }, [refreshData])

  return {
    data,
    hbConfig,
    setHbConfig,
    fallbackConfig,
    setFallbackConfig,
    isLoading,
    lastSync,
    refreshData,
  }
}
