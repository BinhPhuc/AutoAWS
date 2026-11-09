import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it } from 'vitest'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

const fixture = (
  <Dialog defaultOpen>
    <DialogContent>
      <DialogTitle>Connection form</DialogTitle>
      <DialogDescription>Enter connection details</DialogDescription>
      <Input aria-label="Connection name" defaultValue="My account" />
      <Dialog>
        <DialogTrigger render={<Button type="button" />}>Open role help</DialogTrigger>
        <DialogContent>
          <DialogTitle>Role help</DialogTitle>
          <DialogDescription>Role instructions</DialogDescription>
          <Button type="button">Read instructions</Button>
        </DialogContent>
      </Dialog>
    </DialogContent>
  </Dialog>
)

afterEach(cleanup)

it('closes only the help popup on outside click and keeps the connection values', async () => {
  const user = userEvent.setup()
  render(fixture)
  await user.click(screen.getByRole('button', { name: 'Open role help' }))
  expect(screen.getByRole('dialog', { name: 'Role help' })).toBeInTheDocument()
  const overlays = document.querySelectorAll('[data-slot="dialog-overlay"]')
  expect(overlays).toHaveLength(2)
  await user.click(overlays[1])
  await waitFor(() =>
    expect(screen.queryByRole('dialog', { name: 'Role help' })).not.toBeInTheDocument(),
  )
  expect(screen.getByRole('dialog', { name: 'Connection form' })).toBeInTheDocument()
  expect(screen.getByRole('textbox', { name: 'Connection name' })).toHaveValue('My account')
  await user.click(document.querySelector('[data-slot="dialog-overlay"]')!)
  await waitFor(() =>
    expect(screen.queryByRole('dialog', { name: 'Connection form' })).not.toBeInTheDocument(),
  )
})

it('keeps the help open on an inside click and closes only it on Escape', async () => {
  const user = userEvent.setup()
  render(fixture)
  await user.click(screen.getByRole('button', { name: 'Open role help' }))
  await user.click(screen.getByRole('button', { name: 'Read instructions' }))
  expect(screen.getByRole('dialog', { name: 'Role help' })).toBeInTheDocument()
  await user.keyboard('{Escape}')
  await waitFor(() =>
    expect(screen.queryByRole('dialog', { name: 'Role help' })).not.toBeInTheDocument(),
  )
  expect(screen.getByRole('textbox', { name: 'Connection name' })).toHaveValue('My account')
})
