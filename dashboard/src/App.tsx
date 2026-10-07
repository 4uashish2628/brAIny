import { RunPage } from './RunPage'
import { RunsPage } from './RunsPage'
import { TrialPage } from './TrialPage'
import { useRoute } from './lib'
import { Shell } from './ui'

export default function App() {
  const route = useRoute()
  return (
    <Shell>
      {route.page === 'runs' && <RunsPage />}
      {route.page === 'run' && <RunPage key={route.id} id={route.id} />}
      {route.page === 'trial' && <TrialPage key={route.id} id={route.id} />}
    </Shell>
  )
}
