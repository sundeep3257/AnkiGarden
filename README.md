# AnkiGarden

A beautiful garden mini-game add-on for Anki that gamifies your study sessions by rewarding consistent review streaks with garden items, coins, and visual progress.

## 🌱 What is AnkiGarden?

AnkiGarden transforms your Anki study routine into an engaging gardening experience. As you review cards correctly, you earn rewards that let you build and maintain a personalized 15x7 garden. Watch your garden flourish as your knowledge grows!

## 💡 Why is it Helpful?

- **Gamification**: Makes studying more engaging and fun by adding game-like rewards and progression
- **Visual Motivation**: Provides a tangible, visual representation of your study progress and consistency
- **Streak Incentives**: Encourages maintaining review streaks by rewarding consecutive correct answers
- **Long-term Engagement**: The garden requires ongoing care, creating a daily habit of checking in and studying
- **Stress Relief**: Offers a relaxing, creative outlet during study breaks
- **Achievement System**: Unlock new themes and rare items as you progress, giving you goals to work toward

## ✨ Features

### 🎮 Core Gameplay

- **Review Streak Tracking**: Automatically tracks your correct answer streaks during study sessions
- **Reward System**: Earn items based on your streak milestones:
  - 15 correct answers in a row: +1 Water 💧
  - 30 correct answers in a row: +1 Plant 🌱
  - 50 correct answers in a row: +1 Tree 🌳
  - Every correct answer: +1 Coin 🪙
- **Garden Management**: Build and customize your 15x7 tile garden with plants, trees, seeds, and decorative paths

### 🌿 Garden Items

- **Plants**: Single-tile plants that need regular watering to stay healthy
- **Trees**: Large 2x2 trees that require 4 water to maintain
- **Seeds**: Special items that evolve over time:
  - Week 1: Evolves into a colorful plant with vibrant flowers
  - Week 2: Evolves into a beautiful cherry blossom tree (2x2)
- **Paths**: Decorative walkways that can be placed between tiles for aesthetic customization

### 💧 Plant Care System

- **Watering Mechanics**: Plants, trees, and seeds require regular watering:
  - Plants: Need water every 1-2 days (die after 3 days without water)
  - Trees: Need water every 1-2 days (die after 2 days without water)
  - Seeds: Need water every 1-2 days (die after 2 days without water)
- **Sunlight Power**: Apply sunlight tokens to make everything in your garden bloom for 1 day
- **Lifecycle Management**: Remove dead items and maintain a healthy garden

### 🛒 Shop System

Use your hard-earned coins to purchase:
- Water: 20 coins
- Plant: 50 coins
- Tree: 100 coins
- Sunlight: 200 coins
- Seed: 1000 coins (rare and valuable!)
- Path: 20 coins

### 🎨 Aesthetic Themes

Unlock and switch between multiple garden themes (2000 coins each):
- **Default**: Classic garden aesthetic
- **Night Garden**: Dark, serene nighttime atmosphere
- **Summer Garden**: Bright, warm summer vibes
- **Winter Garden**: Cool, peaceful winter scene
- **Spring Garden**: Fresh, blooming spring colors
- **Autumn Garden**: Warm, cozy autumn tones

### 📊 Inventory Management

Track all your resources in real-time:
- Water 💧
- Plants 🌱
- Trees 🌳
- Sunlight ☀️
- Coins 🪙
- Seeds 🌰
- Paths 🪨

### 🎯 User Interface

- **Interactive Garden View**: Click-based placement and management system
- **Action Buttons**: Easy-to-use buttons for all garden operations
- **Mode Switching**: Intuitive modes for placing, watering, and removing items
- **Built-in Instructions**: Comprehensive help dialog accessible from the garden interface
- **Fast Forward**: Speed up animations when desired

## 📦 Installation

1. Download the add-on from [AnkiWeb](https://ankiweb.net/shared/addons/) (search for "AnkiGarden")
2. Open Anki and go to `Tools` → `Add-ons`
3. Click `Install from file...` and select the downloaded `.ankiaddon` file
4. Restart Anki to activate the add-on

Alternatively, you can install directly from AnkiWeb using the add-on code.

## 🚀 Getting Started

1. After installation, you'll start with:
   - 1 Plant 🌱
   - 3 Waters 💧
   - 0 Coins 🪙

2. Access your garden by going to `Tools` → `AnkiGarden` in the Anki menu

3. Place your first plant and start studying! As you review cards correctly, you'll earn:
   - Coins for every correct answer
   - Special rewards for maintaining streaks

4. Use your coins in the shop to expand your garden, or save up for rare seeds and theme unlocks

5. Remember to water your plants regularly to keep them healthy!

## 📋 Requirements

- Anki 2.1.0 or later
- Python 3.6+ (included with Anki)

## 🎓 Tips for Success

- **Maintain Streaks**: Focus on accuracy to build long streaks and earn better rewards
- **Regular Watering**: Check your garden daily and water plants before they die
- **Save for Seeds**: Seeds are expensive but evolve into beautiful cherry blossom trees
- **Plan Your Layout**: Think about your garden design before placing items
- **Use Sunlight Wisely**: Save sunlight tokens for special moments when you want everything to bloom
- **Explore Themes**: Unlock different themes to find your favorite aesthetic

## 🔧 Technical Details

- **State Persistence**: Garden state is saved in `ankigarden_state.json` in the add-on directory
- **Schema Versioning**: Includes migration support for future updates
- **Lightweight**: Minimal performance impact on Anki reviews
- **Error Handling**: Fails silently to prevent disrupting your study sessions

## 📝 License

This add-on is available for use with Anki. Please refer to the license terms on AnkiWeb.

## 🤝 Contributing

Found a bug or have a feature request? Please report issues on the AnkiWeb add-on page or through the appropriate channels.

---

**Happy Gardening!** 🌱🌳🌸

Transform your study routine into a beautiful, rewarding experience with AnkiGarden.

