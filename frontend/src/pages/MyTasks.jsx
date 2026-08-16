import { Card } from '../components/ui'
import TaskList from '../components/TaskList'

export default function MyTasks() {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">My tasks</h1>
        <p className="mt-1 text-sm text-slate-500">
          Everything you need to complete as part of onboarding. Document items tick themselves
          once HR approves the upload.
        </p>
      </div>

      <Card>
        <TaskList self />
      </Card>
    </div>
  )
}
