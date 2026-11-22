# Social media: Instagram, LinkedIn, X (research, 2026-11-22)

How Hermes can post to and watch Instagram, LinkedIn and X with as few API calls and model calls
as possible, and three spending scenarios: $0, $5 and $20 a month. Nothing here is built yet.

**About the sources:** most prices and limits come from third-party guides (Meta, LinkedIn and X's
own pages were often unreachable or contradict each other). Check each one in the platform's
console before relying on it. Sources are listed at the end.

**Budgets** are extra US dollars a month on top of what is already paid for (the AWS host and
Claude Pro). Rough rupee figures: $5 ≈ ₹430, $20 ≈ ₹1,700.

## Rule for every scenario: models write once a week, scripts do the rest

- **Writing:** one Claude Pro session a week writes the whole week in one file
  (`content/week-NN.md` in the handoff repo): each post with its X, LinkedIn and Instagram versions.
  Claude Pro is already paid for, so this adds nothing to the budget.
- **Scripts (0 model calls):** check lengths and structure, add hashtags from a fixed list, keep
  links out of X posts, schedule, post, confirm the post is live, mark it done, alert Telegram.
- **Gemini free tier (optional):** one batched call a day to sort mentions/comments, one a week
  for a short growth note. Flash-Lite's 500 requests a day are far more than this needs.
- **Approval:** one Telegram card per post (`yes` / `edit` / `skip`), same pattern as `/hr` and `/slack`.

## Every free way to work with each platform

### Instagram

| Method | What it does | Cost / limits | Risk |
|---|---|---|---|
| **Official API (Instagram Login)** | Publish photos, carousels (2–10 items), reels, stories; reply to comments; read insights | Free. Business or Creator account plus a Meta app in development mode for your own account (no app review). Limit reported as 25, 50 or 100 posts a day: `GET /<IG_USER_ID>/content_publishing_limit` gives the real number. Media must be at a public URL (a presigned S3 link from the AWS host). Token lasts 60 days and can be refreshed by a script. | Low |
| **Webhooks** | Push events for new comments and @mentions to Hermes' existing webhook receiver (`gateway/platforms/webhook*.py`) | Free, no polling, so 0 API calls while nothing happens | Low |
| **Meta Business Suite scheduler** | Schedule posts and reels by hand in a browser | Free | None |
| **Notification emails** | Instagram emails about comments, follows and mentions; the brief already reads Gmail/Outlook | Free | None |
| **Buffer free plan** | One of 3 free channels, 10 queued posts | Free | None |
| Browser automation | Not needed: the API covers everything | — | High |

Since September 2026 the API also takes `is_ai_generated=true` for the AI label.

### LinkedIn

| Method | What it does | Cost / limits | Risk |
|---|---|---|---|
| **"Share on LinkedIn" API (personal profile)** | Post text, images, video, PDF documents (carousels) as you | Free and self-serve (no review). About 100–150 calls a day per member. Login lasts about 60 days, then you log in again (one Telegram reminder). Cannot read comments, post history or analytics. | Low |
| **Community Management API (company page)** | Post as the page, read page stats and comments | Free, but needs an application, a page admin role and a review. Takes weeks, may be refused. | Low |
| **Built-in scheduling** | Schedule a personal or page post by hand | Free | None |
| **Buffer free plan** | Company page and/or profile as free channels, 10 queued each | Free | None |
| **Notification emails** | Comments, reactions, mentions, connection requests | Free; the only free way to see LinkedIn comments | None |
| Browser automation (dummy account, then real) | Comments on other people's posts, DMs, connection requests: no API exists for these | Free | High: against LinkedIn's rules. Run from your own machine (home IP), human pace, dry-run first. Never from AWS. |

### X

| Method | What it does | Cost / limits | Risk |
|---|---|---|---|
| **Built-in scheduler on x.com (web)** | Schedule single posts by hand | Free for all accounts, web only; threads can't be scheduled. One outlier source says Premium is needed: check. | None |
| **Buffer free plan** | X as a free channel; Buffer posts through its own API access | Free; 10 queued posts and 1 thread per channel at a time, so 2 posts a day means a refill twice a week | None |
| **Notification emails** | Mentions, replies, follows | Free; the free way to see mentions | None |
| **Browser automation** | Fill the x.com scheduler once a week in one session, or post at 1pm/8pm | Free | Medium from your own machine, high from AWS (datacenter IP; the earlier decision accepted this risk). Batch scheduling once a week is safer than logging in twice a day. |
| Pay-per-use API | Post, read mentions, read metrics, delete | **No free tier for new developers since 6 Feb 2026.** About $0.015 per post, $0.20 per post with a link, $0.005 per post read, $0.010 per summoned reply. New accounts get one-time trial credits (reported as $20 plus a match up to $50). | Low |
| Self-hosted Postiz | Calendar UI and its own API in front of the platforms | Free (AGPL) but it uses your own X app keys, so X posts still cost the API price. Check its Instagram/LinkedIn support before choosing. | Low |
| Free X API tier | — | Gone for new sign-ups. | — |

## Ways to start a workflow

| Trigger | Example | Model calls |
|---|---|---|
| Hermes cron, no-agent mode | Post approved items at 1pm and 8pm; refresh the Instagram token every 50 days; LinkedIn login reminder at day 55 | 0 |
| Handoff repo push | Claude pushes `content/week-NN.md`; cron `git pull` checks it and sends approval cards | 0 |
| Telegram command | `/post queue`, `/post yes <id>`, `/post now <id>`, `/post skip <id>`, `/post take <id>` (takedown) | 0 |
| Telegram forward | Forward a photo, link or note to the bot: saved as an idea for the next Claude session | 0 |
| Google Sheet calendar (optional) | A row set to `approved` gets scheduled by the sync script | 0 |
| Platform webhook | New Instagram comment or mention: Telegram alert | 0 (1 batched Gemini call a day if you want sorting) |
| Notification email | X mention, LinkedIn comment: added to the daily digest | 0 (same optional call) |
| Media folder | Raw video dropped in a folder: `scripts/media/editplan.py` renders a vertical reel with captions into the queue | 0 |

## Scenario A: $0 a month

| Platform | Posting | Watching |
|---|---|---|
| Instagram | Official API, fully automatic after your `yes` | Webhooks + insights API (free) |
| LinkedIn profile | Official API, fully automatic | Notification emails |
| LinkedIn page | Buffer free channel, or built-in scheduling. Fill it from the weekly pack (Telegram sends ready-to-paste text). Apply for the Community Management API meanwhile. | Notification emails |
| X | Buffer free channel (refill twice a week), or the x.com scheduler filled once a week by hand or by browser automation from your machine | Notification emails |

- **Your time:** about 10 minutes, twice a week, pasting X (and page) posts; 0 if you accept browser-automation risk.
- **Model calls:** 0 per post; at most 1 Gemini free call a day.
- **Gaps:** no X metrics (copy them from x.com analytics by hand if needed), no automatic X replies,
  no LinkedIn comment reading beyond emails.

## Scenario B: $5 a month

Everything in A, plus the X pay-per-use API for X posting and mentions.

| X item | Volume | Cost |
|---|---|---|
| 2 original posts a day, no links | 60 a month | $0.90 |
| Read mentions once a day | ~25 a day, 750 a month | $3.75 |
| Metrics for your own posts, read once a day | ~60 reads | $0.30 |
| **Total** | | **≈ $4.95** |

- X becomes fully automatic and risk-free: post, verify live, mark done, takedown by command.
- Links: one link post costs $0.20; keep links in the Instagram bio / LinkedIn, or post linked X posts by hand.
- The new-account trial credits should cover the first several months.
- Buffer is then needed only for the LinkedIn company page (until the review comes through).

## Scenario C: $20 a month

Everything in B, plus replies and paid scheduling for the page. Pick lines to fit:

| Item | Cost |
|---|---|
| X posts + mentions + metrics (scenario B) | ≈ $5 |
| X replies, ~15 a day (approved in one daily batch; needs the "Automated" label on the account) | ≈ $6.75 |
| 2–3 link posts a month on X | ≈ $0.60 |
| Buffer Essentials, 1 channel (LinkedIn page: unlimited queue, analytics) | $6 (monthly billing) |
| **Total** | **≈ $18.35** |

Alternative for the last $6–8: X Premium (₹650 a month in India, reported) for longer posts, edits
and reach, instead of Buffer, if the Community Management API review succeeds.

Kabir's old 45 replies a day would be about $20 on their own, and 45 automated replies a day is a
policy risk, so 15 a day is the suggested cap.

## Recommendation

Start with **scenario A for Instagram and LinkedIn profile** (both free, official, fully automatic)
and **scenario B for X** (about $5, the only route where X is automatic and has no ban risk).
Use Buffer's free plan for the LinkedIn company page while the API application is reviewed.
Keep browser automation only for LinkedIn comments and DMs, on the dummy account, from your own machine.

## Open questions for you

1. X: pay-per-use API (B) or stay free with Buffer / scheduler (A)?
2. LinkedIn: personal profile, company page, or both?
3. Instagram: is the account already Business or Creator, and linked to a Facebook page?
4. Who approves: you alone on Telegram, or someone else too?

## Sources

- [Blotato: X API pricing 2026](https://www.blotato.com/blog/twitter-api-pricing)
- [Outstand: X API pricing 2026](https://www.outstand.so/blog/x-api-pricing)
- [Postproxy: X API pricing 2026](https://postproxy.dev/blog/x-api-pricing-2026/)
- [OpenTweet: X API price table](https://opentweet.io/x-api-pricing)
- [Upload-Post: X API pricing 2026](https://www.upload-post.com/x-api-pricing/)
- [SocialCrawl: X API in 2026](https://www.socialcrawl.dev/blog/x-twitter-api-2026)
- [TwitterAPIs: is the Twitter API free in 2026](https://www.twitterapis.com/blogs/is-twitter-api-free)
- [Tweetviewer: scheduling posts on X natively](https://tweetviewer.com/blog/how-to-schedule-posts-on-x)
- [Lilach Bullock: how to schedule a post on X](https://www.lilachbullock.com/how-to-schedule-a-post-on-x/)
- [Lilach Bullock: X Premium price in India](https://www.lilachbullock.com/x-premium-price-in-india/)
- [Meta: Instagram content publishing](https://developers.facebook.com/docs/instagram-platform/content-publishing/)
- [Meta: Instagram publishing limit endpoint](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/content_publishing_limit)
- [Meta: Instagram platform changelog](https://developers.facebook.com/docs/instagram-platform/changelog)
- [bundle.social: Instagram posting API](https://bundle.social/blog/instagram-posting-api)
- [Microsoft Learn: LinkedIn Posts API](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api)
- [Microsoft Learn: LinkedIn getting access](https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access)
- [Zernio: LinkedIn posting API](https://zernio.com/blog/linkedin-posting-api)
- [OpenTweet: is the LinkedIn API free](https://opentweet.io/answers/is-the-linkedin-api-free)
- [Buffer pricing](https://buffer.com/pricing)
- [Buffer: features on each plan](https://support.buffer.com/article/595-features-available-on-each-buffer-plan)
- [Postiz on GitHub](https://github.com/gitroomhq/postiz-app)
- [Postiz public API](https://docs.postiz.com/public-api/introduction.md)
