import Image from 'next/image';
import Link from 'next/link';
import { Box, Button, Card, Flex, Heading, Text } from '@radix-ui/themes';

const steps = [
  {
    title: 'Open your Superhuman Docs API settings',
    description: 'Go to your account’s API settings. Sign in to Superhuman Docs if prompted.',
    image: '/guides/superhuman-generate-token.png',
    url: 'https://docs.superhuman.com/account#apiSettings',
    width: 939,
    height: 202,
    alt: 'Superhuman Docs API settings with the Generate API token button',
  },
  {
    title: 'Start creating a token',
    description: 'Select Generate API token. Give the token any memorable name, then expand Add a restriction.',
    image: '/guides/superhuman-token-name.png',
    width: 736,
    height: 355,
    alt: 'Generate new token dialog with a name field and Add a restriction section',
  },
  {
    title: 'Choose read-only MCP access',
    description: 'Set Type of restriction to MCP and Type of access to Read only, then generate the token.',
    image: '/guides/superhuman-token-restrictions.png',
    width: 668,
    height: 503,
    alt: 'Token restriction settings showing MCP and Read only selected',
  },
];

export default function SuperhumanGuidePage() {
  return (
    <Box p={{ initial: '4', md: '6' }} style={{ maxWidth: 960, margin: '0 auto' }}>
      <Link href="/chat" style={{ color: 'var(--accent-11)', textDecoration: 'none' }}>
        ← Back to chat
      </Link>
      <Heading size="7" mt="4" mb="2">Connect Superhuman Docs</Heading>
      <Text as="p" size="3" color="gray" mb="5">
        Create a personal, read-only token and paste it into the Superhuman Docs connection in chat.
      </Text>

      <Flex direction="column" gap="4">
        {steps.map((step, index) => (
          <Card key={step.title} size="3">
            <Flex direction="column" gap="3">
              <Box>
                <Text size="1" weight="bold" color="gray">STEP {index + 1}</Text>
                <Heading size="4" mt="1" mb="1">{step.title}</Heading>
                <Text as="p" color="gray">{step.description}</Text>
                {'url' in step && (
                  <Text as="p" size="2" mt="2">
                    <Link href={step.url} target="_blank" rel="noreferrer">
                      {step.url}
                    </Link>
                  </Text>
                )}
              </Box>
              <Image
                src={step.image}
                alt={step.alt}
                width={step.width}
                height={step.height}
                unoptimized
                sizes="(max-width: 960px) 100vw, 880px"
                style={{ width: '100%', height: 'auto', borderRadius: 'var(--radius-2)', border: '1px solid var(--gray-a6)' }}
              />
            </Flex>
          </Card>
        ))}
      </Flex>

      <Card size="3" mt="4">
        <Heading size="4" mb="2">Add your token</Heading>
        <Text as="p" color="gray" mb="3">
          Return to chat, choose Connect for Superhuman Docs, and paste the token into the personal token field.
          The token is used only for your personal connection.
        </Text>
        <Flex gap="3" align="center" wrap="wrap">
          <Button asChild>
            <Link href="/chat">Go to chat</Link>
          </Button>
          <Link href="https://docs.superhuman.com/account#apiSettings" target="_blank" rel="noreferrer">
            Open Superhuman Docs API settings
          </Link>
        </Flex>
      </Card>
    </Box>
  );
}
