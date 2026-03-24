import { expect, test } from '@playwright/test'

test('home page smoke test', async ({ page }) => {
  await page.goto('/')

  await expect(page).toHaveTitle(/LocalVideo/)
  await expect(page.getByText('LocalVideo')).toBeVisible()
  await expect(page.getByRole('heading', { name: '我的项目' })).toBeVisible()
})
